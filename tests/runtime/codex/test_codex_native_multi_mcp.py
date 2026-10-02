"""Three real MCP sources -> same CLI -> follow-up using returned values."""

import asyncio
import contextlib
import json
import os
from pathlib import Path

import pytest
import uvicorn
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from native_parity_http import NativeHTTPBackend
from native_parity_support import save_result, sha
from openai_codex import AsyncCodex, CodexConfig
from openai_codex.generated.v2_all import Personality, ReasoningEffort

from veadk import Agent, Runner
from veadk.runtime.codex import runtime
from veadk.runtime.codex.config import CodexRuntimeConfig, codex_subprocess_env
from veadk.runtime.codex.native_bridge import NativeBridge


@pytest.mark.codex_native
@pytest.mark.parametrize("hint", [None, False, True])
@pytest.mark.parametrize("stack", ["official", "veadk"])
def test_three_mcp_sources_execute_and_feed_followup(
    tmp_path, stack, hint, monkeypatch
):
    monkeypatch.setenv("PARITY_CAUSE_OUTPUT", str(tmp_path))
    asyncio.run(asyncio.wait_for(scenario(tmp_path, stack, hint), 90))


@pytest.mark.codex_native
@pytest.mark.parametrize("hint", [None, False], ids=["missing", "false"])
def test_explicit_server_parallelism_preserves_provider_annotations(
    tmp_path, hint, monkeypatch
):
    original_specs = runtime.native_mcp_tool_specs
    observed = []

    def checked_specs(bundle):
        specs = original_specs(bundle)
        observed.extend(specs)
        assert len(specs) == 3
        assert all(
            spec.get("annotations", {}).get("readOnlyHint") is hint for spec in specs
        )
        return specs

    monkeypatch.setattr(runtime, "native_mcp_tool_specs", checked_specs)
    monkeypatch.setenv("PARITY_CAUSE_OUTPUT", str(tmp_path))
    asyncio.run(
        asyncio.wait_for(scenario(tmp_path, "veadk", hint, server_parallel=True), 90)
    )
    assert len(observed) == 3


async def scenario(root, stack, hint, *, server_parallel=False):
    names = ("alpha", "beta", "gamma")
    calls, services = [], []
    active, peak = 0, 0
    urls = {}
    bridge = None

    async def start(app):
        server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=0, log_level="critical", access_log=False
            )
        )
        task = asyncio.create_task(server.serve())
        services.append((server, task))
        while not server.started:
            if task.done():
                await task
            await asyncio.sleep(0.01)
        return f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}/mcp"

    def add_tool(mcp, source):
        @mcp.tool(
            description=f"Read a synthetic value from source {source}.",
            annotations=ToolAnnotations(readOnlyHint=hint)
            if hint is not None
            else None,
        )
        async def lookup(value: str) -> dict:
            """Read a value from this synthetic source."""
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.1)
                calls.append({"source": source, "argument": value})
                return {
                    "observed": source + ":" + value,
                    "followup": "returned-by-" + source,
                }
            finally:
                active -= 1

    class Backend(NativeHTTPBackend):
        def _script(self, body):
            try:
                return self.script(body)
            except Exception as error:
                save_result(
                    Path(os.environ["PARITY_CAUSE_OUTPUT"])
                    / (stack + "-request-error-" + str(len(self.requests)) + ".json"),
                    {
                        "exception_type": type(error).__name__,
                        "tool_names": [
                            t.get("function", t).get("name")
                            for t in body.get("tools", [])
                        ],
                        "output_call_ids": [
                            item.get("call_id")
                            for item in body.get("input", [])
                            if item.get("type") == "function_call_output"
                        ],
                        "provider_call_count": len(calls),
                    },
                )
                raise

        def script(self, body):
            tools = [t.get("function", t) for t in body.get("tools", [])]
            available = {
                source: next(
                    t
                    for t in tools
                    if f"source {source}." in t.get("description", "")
                    and "lookup" in t.get("name", "")
                )
                for source in names
            }
            index = len(self.requests)
            if index == 1:
                output = [
                    self._function_call(
                        available[source]["name"],
                        {"value": "first"},
                        call_id="core-" + source,
                    )
                    for source in names
                ]
            else:
                history = {
                    item["call_id"]: item["output"]
                    for item in body["input"]
                    if item.get("type") == "function_call_output"
                }
                # Actual returned source values must be in the next model input,
                # paired with the requested call IDs, once each.
                for source in names:
                    encoded = json.dumps(history["core-" + source], ensure_ascii=False)
                    assert source + ":first" in encoded
                    assert "returned-by-" + source in encoded
                    assert (
                        sum(
                            item.get("call_id") == "core-" + source
                            and item.get("type") == "function_call_output"
                            for item in body["input"]
                        )
                        == 1
                    )
                if index == 2:
                    # The next call uses data supplied by a different MCP source.
                    encoded = json.dumps(history["core-beta"])
                    followup = next(
                        value
                        for value in (
                            "returned-by-alpha",
                            "returned-by-beta",
                            "returned-by-gamma",
                        )
                        if value in encoded
                    )
                    output = [
                        self._function_call(
                            available["alpha"]["name"],
                            {"value": followup},
                            call_id="core-followup",
                        )
                    ]
                else:
                    assert index == 3
                    assert "alpha:returned-by-beta" in json.dumps(
                        history["core-followup"]
                    )
                    output = [self._message("multi-source-results-used-exactly")]
            return self._response(body, output)

    backend = Backend()
    try:
        for source in names:
            mcp = FastMCP(source, stateless_http=True, json_response=True)
            add_tool(mcp, source)
            urls[source] = await start(mcp.streamable_http_app())
        model_url = await backend.start()
        config = CodexRuntimeConfig(
            integration_mode="native",
            mcp_supports_parallel_tool_calls=server_parallel,
            responses_tool_format="functions",
            web_search="disabled",
            sandbox="read_only",
            personality="none",
            reasoning_effort="high",
            workspace_root=str(root / "workspaces"),
            session_root=str(root / "sessions"),
        )
        if stack != "official":
            toolsets = [
                McpToolset(
                    connection_params=StreamableHTTPConnectionParams(url=url),
                    tool_name_prefix=source,
                )
                for source, url in urls.items()
            ]
            agent = Agent(
                name="synthetic",
                runtime="codex",
                model_name="synthetic",
                model_api_base=model_url + "/v1",
                model_api_key="synthetic",
                model_api_key_name="",
                tools=toolsets,
                codex_runtime_config=config,
            )
            runner = Runner(agent=agent, app_name="synthetic")
            await runner.short_term_memory.create_session(
                app_name="synthetic", user_id="u", session_id="s"
            )
            stream = runner.run_async(
                user_id="u",
                session_id="s",
                new_message=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text="Read three sources and follow the returned cross-source value."
                        )
                    ],
                ),
            )
            async with contextlib.aclosing(stream):
                events = [event async for event in stream]
            assert not any(event.error_code for event in events)
            finals = [
                event
                for event in events
                if event.is_final_response()
                and event.content
                and any(p.text for p in event.content.parts or [])
            ]
            assert len(finals) == 1
            final = "\n".join(p.text for p in finals[0].content.parts if p.text)
        else:
            # Only the reversible wire-format adapter is shared. Official CLI
            # connects directly to each source MCP endpoint, retaining metadata.
            bridge = NativeBridge(
                model_url + "/v1", "synthetic", tool_format="functions"
            )
            await bridge.start()
            token = bridge.register_turn([], {})
            home, workspace = root / "home", root / "workspace"
            home.mkdir()
            workspace.mkdir()
            runtime._prepare_codex_home(bridge.url, "synthetic", config, home=str(home))
            with (home / "config.toml").open("a") as handle:
                for source, url in urls.items():
                    handle.write(
                        f'\n[mcp_servers.{source}]\nurl = "{url}"\nrequired = true\ndefault_tools_approval_mode = "approve"\n'
                    )
            async with AsyncCodex(
                config=CodexConfig(
                    cwd=str(workspace), env=codex_subprocess_env(str(home), token)
                )
            ) as codex:
                thread = await codex.thread_start(
                    model="synthetic",
                    model_provider="veadk",
                    cwd=str(workspace),
                    approval_mode=runtime._approval_mode(config),
                    sandbox=runtime._sandbox(config),
                    personality=Personality.none,
                )
                result = await thread.run(
                    "Read three sources and follow the returned cross-source value.",
                    effort=ReasoningEffort.high,
                )
                final = result.final_response
        assert final == "multi-source-results-used-exactly"
        assert len(calls) == 4 and len(backend.requests) == 3
        assert calls[-1] == {"source": "alpha", "argument": "returned-by-beta"}
        assert peak == (3 if hint or server_parallel else 1)
        save_result(
            Path(os.environ["PARITY_CAUSE_OUTPUT"]) / (stack + ".json"),
            {
                "stack": stack,
                "sources": len(urls),
                "provider_calls": calls,
                "model_requests": len(backend.requests),
                "peak": peak,
                "call_ids_and_result_use_verified": True,
                "final_sha256": sha(final),
            },
        )
    finally:
        if bridge is not None:
            await bridge.stop()
        await backend.stop()
        for server, task in reversed(services):
            server.should_exit = True
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(task, 5)
