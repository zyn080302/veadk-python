"""Synthetic-only SDK/veADK differential harness; no live data or credentials."""

import asyncio
import contextlib
import hashlib
import json
import time
from pathlib import Path

from google.genai import types
from native_parity_http import NativeHTTPBackend
from openai_codex import AsyncCodex, CodexConfig, TextInput
from openai_codex.generated.v2_all import Personality, ReasoningEffort

from veadk import Agent, Runner
from veadk.runtime.codex import runtime
from veadk.runtime.codex.config import CodexRuntimeConfig, codex_subprocess_env
from veadk.runtime.codex.native_bridge import NativeBridge

FINAL = "## 合成最终报告\n\n保留原始空白与 CRLF\r\n结果。\n"
PROGRESS = "合成成稿进展，不能并入报告。\n"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ScriptedBackend(NativeHTTPBackend):
    def __init__(self, scenario):
        super().__init__()
        self.scenario = scenario

    def message(self, text, phase=None):
        item = self._message(text)
        if phase:
            item["phase"] = phase
        return item

    def _script(self, body):
        scenario = self.scenario
        if scenario in {"tool_then_progress", "parallel", "explicit_before_tool"}:
            if len(self.requests) == 1:
                tool = next(
                    t for t in body["tools"] if "synthetic_read" in t.get("name", "")
                )
                count = 4 if scenario == "parallel" else 1
                output = [
                    self._function_call(
                        tool["name"], {"value": str(n)}, call_id=f"call_{n}"
                    )
                    for n in range(count)
                ]
                if scenario == "explicit_before_tool":
                    output.insert(0, self.message(PROGRESS, "final_answer"))
                if scenario == "tool_then_progress":
                    output.append(self.message(PROGRESS))
            else:
                assert len(self.requests) == 2
                output = [self.message(FINAL)]
        else:
            assert len(self.requests) == 1
            phases = {
                "unphased_pair": (None, None),
                "commentary_then_final": ("commentary", "final_answer"),
                "two_finals": ("final_answer", "final_answer"),
                "explicit_then_unphased": ("final_answer", None),
            }[scenario]
            output = [self.message(PROGRESS, phases[0]), self.message(FINAL, phases[1])]
        return self._response(body, output)


def select_native_final(events):
    """Experimental selector matching official SDK; does not edit installed code."""
    last_unknown = None
    for event in reversed(events):
        phase = (event.custom_metadata or {}).get("phase")
        if phase == "final_answer":
            return event
        if phase is None and last_unknown is None:
            last_unknown = event
    return last_unknown


async def run_stack(root, stack, scenario):
    root.mkdir(parents=True)
    backend = ScriptedBackend(scenario)
    url = await backend.start()
    calls, active, peak = [], 0, 0

    async def synthetic_read(value: str) -> dict:
        """Return synthetic data without side effects."""
        nonlocal active, peak
        started = time.monotonic()
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.2)
            return {"value": value, "observed": True}
        finally:
            active -= 1
            calls.append({"value": value, "start": started, "end": time.monotonic()})

    config = CodexRuntimeConfig(
        integration_mode="native",
        responses_tool_format="functions",
        web_search="disabled",
        sandbox="read_only",
        reasoning_effort="high",
        personality="none",
        session_root=str(root / "sessions"),
        workspace_root=str(root / "workspaces"),
    )
    notes = []
    try:
        if stack == "veadk":
            agent = Agent(
                name="synthetic",
                instruction="Return only synthetic data.",
                runtime="codex",
                model_name="synthetic",
                model_api_base=url + "/v1",
                model_api_key="synthetic",
                model_api_key_name="",
                tools=[synthetic_read],
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
                    role="user", parts=[types.Part(text="synthetic original task")]
                ),
            )
            async with contextlib.aclosing(stream):
                events = [event async for event in stream]
            assert not any(e.error_code for e in events)
            finals = [
                e
                for e in events
                if e.is_final_response()
                and e.content
                and any(p.text for p in e.content.parts or [])
            ]
            assert len(finals) == 1
            # Preserve part boundaries: SDK/ADK consumers join parts, rather than
            # silently stripping text when comparing final-answer semantics.
            parts = [p.text for p in finals[0].content.parts if p.text]
            final = "\n".join(parts)
            for event in events:
                meta = event.custom_metadata or {}
                if meta.get("item_type") == "agentMessage":
                    notes.append(
                        {"phase": meta.get("phase"), "partial": bool(event.partial)}
                    )
        else:
            bridge = NativeBridge(url + "/v1", "synthetic", tool_format="functions")
            await bridge.start()

            async def execute(arguments, call_id):
                return json.dumps(await synthetic_read(**arguments))

            token = bridge.register_turn(
                [
                    {
                        "name": "synthetic_read",
                        "description": "Read synthetic data.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                        },
                    }
                ],
                {"synthetic_read": execute},
            )
            workspace = root / "workspace"
            workspace.mkdir()
            home = root / "home"
            home.mkdir()
            runtime._prepare_codex_home(bridge.url, "synthetic", config, home=str(home))
            with (home / "config.toml").open("a") as stream:
                stream.write(
                    f'\n[mcp_servers.veadk]\nurl = "{bridge.url}/mcp"\nbearer_token_env_var = "VEADK_CODEX_API_KEY"\nrequired = true\ndefault_tools_approval_mode = "approve"\n'
                )
            try:
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
                    # Official SDK collection/selection; no veADK event codec.
                    result = await thread.run(
                        [TextInput("synthetic original task")],
                        effort=ReasoningEffort.high,
                    )
                    final = result.final_response
                    for item in result.items:
                        item = item.root if hasattr(item, "root") else item
                        if getattr(item, "type", None) == "agentMessage":
                            notes.append(
                                {
                                    "phase": getattr(item.phase, "value", item.phase),
                                    "text_sha256": sha(item.text),
                                }
                            )
            finally:
                bridge.unregister_turn(token)
                await bridge.stop()
        assert isinstance(final, str)
        return {
            "runtime_source": str(Path(runtime.__file__).resolve()),
            "runtime_sha256": sha(Path(runtime.__file__).read_text()),
            "stack": stack,
            "scenario": scenario,
            "final": final,
            "final_sha256": sha(final),
            "requests": len(backend.requests),
            "peak": peak,
            "calls": calls,
            "messages": notes,
        }
    finally:
        await backend.stop()


def save_result(path, result):
    """Only synthetic text and metadata; exclusive files preserve failures."""
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    with Path(path).open("x") as stream:
        stream.write(payload)
