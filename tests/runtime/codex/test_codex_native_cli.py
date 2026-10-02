"""Mandatory native ownership regression: real CLI, loopback synthetic model."""

import asyncio
import contextlib
import json

import pytest
from google.genai import types
from test_codex_runtime_smoke import _StubResponsesBackend


class NativeBackend(_StubResponsesBackend):
    def _script(self, body):
        # The native route advertises a Codex MCP name, not a shim-injected
        # bare ADK name. Verify it can dispatch a model-produced tool call.
        tools = []
        for spec in body.get("tools", []):
            if spec.get("type") == "namespace":
                tools.extend((spec["name"], tool) for tool in spec.get("tools", []))
            else:
                tools.append((None, spec))
        named = next(
            (
                (ns, t)
                for ns, t in tools
                if "value" in t.get("parameters", {}).get("properties", {})
            ),
            None,
        )
        assert named, "Codex did not advertise the native ADK MCP tool"
        if not self._adk_call_sent:
            self._adk_call_sent = True
            ns, spec = named
            item = self._function_call(
                spec["name"], {"value": "native-result"}, call_id="call_native_1"
            )
            if ns:
                item["namespace"] = ns
            return self._response(body, [item])
        return self._response(body, [self._message("native-final")])


@pytest.mark.codex_native
@pytest.mark.asyncio
async def test_native_cli_through_python_sdk_http(monkeypatch, tmp_path):
    """Real CLI -> real Python SDK -> HTTP -> MCP -> continued native thread."""
    from veadk.runtime.codex.native_bridge import NativeBridge
    from veadk.runtime.codex.native_responses import request_native_stream

    observed = []
    script = NativeBackend._script

    def capture(self, body):
        observed.append(body)
        return script(self, body)

    async def backend(**kwargs):
        kwargs.pop("veadk_tool_names")  # Callback-only names, as in the app adapter.
        return await request_native_stream(**kwargs)

    monkeypatch.setattr(NativeBackend, "_script", capture)
    monkeypatch.setattr(NativeBridge, "response_backend", staticmethod(backend))
    await test_native_cli_owns_tools_and_resumes_thread(tmp_path, None, "functions")
    assert observed and all(isinstance(r["client_metadata"], dict) for r in observed)


@pytest.mark.codex_native
@pytest.mark.asyncio
async def test_native_failure_never_becomes_empty_success(tmp_path):
    from veadk import Agent, Runner
    from veadk.runtime.codex.config import CodexRuntimeConfig

    class FailedBackend(_StubResponsesBackend):
        async def _events(self, result):
            from veadk.runtime.codex.native_transport import encode_backend_result

            async for chunk in encode_backend_result(result):
                yield chunk

        def _script(self, body):
            response = self._response(body, [])
            response.update(
                status="failed",
                error={"code": "invalid_prompt", "message": "synthetic refusal"},
            )
            return response

    backend = FailedBackend()
    url = await backend.start()
    agent = Agent(
        name="failure_test",
        runtime="codex",
        model_name="synthetic",
        model_api_base=url + "/v1",
        model_api_key="synthetic",
        model_api_key_name="",
        codex_runtime_config=CodexRuntimeConfig(
            integration_mode="native",
            session_root=str(tmp_path / "sessions"),
            workspace_root=str(tmp_path / "workspaces"),
        ),
    )
    runner = Runner(agent=agent, app_name="failure_test")
    await runner.short_term_memory.create_session(
        app_name=runner.app_name, user_id="u", session_id="s"
    )
    try:
        stream = runner.run_async(
            user_id="u",
            session_id="s",
            new_message=types.Content(
                role="user", parts=[types.Part(text="fail safely")]
            ),
        )
        async with contextlib.aclosing(stream):
            events = [event async for event in stream]
        assert any(event.error_code for event in events)
        assert not any(
            event.is_final_response() and not event.error_code for event in events
        )
        state = json.loads(
            next((tmp_path / "sessions").glob("*/state.json")).read_text()
        )
        assert state["last_turn_status"] == "failed"
    finally:
        await backend.stop()


@pytest.mark.codex_native
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback_mode,tool_format",
    [
        (None, "native"),
        (None, "functions"),
        ("before", "native"),
        ("after", "native"),
        ("short_circuit", "native"),
    ],
)
async def test_native_cli_owns_tools_and_resumes_thread(
    tmp_path, callback_mode, tool_format
):
    from veadk import Agent, Runner
    from veadk.runtime.codex.config import CodexRuntimeConfig

    calls = []

    def before_model(callback_context, llm_request):
        if callback_mode == "before":
            llm_request.contents[-1].parts[0].text += " callback"
        if (
            callback_mode == "short_circuit"
            and llm_request.contents[-1].parts[0].text == "cached answer"
        ):
            from google.adk.models.llm_response import LlmResponse

            return LlmResponse(
                content=types.Content(
                    role="model", parts=[types.Part(text="callback-cache")]
                )
            )

    def after_model(callback_context, llm_response):
        if callback_mode == "after" and llm_response.content:
            llm_response.content.parts[0].text = "callback-final"

    def native_echo(value: str) -> dict:
        """Return an opaque test value."""
        calls.append(value)
        return {"value": value}

    backend = NativeBackend()
    url = await backend.start()
    agent = Agent(
        name="native_agent",
        instruction="Use the tool then answer.",
        runtime="codex",
        model_name="native-test",
        model_api_base=url + "/v1",
        model_api_key="synthetic",
        model_api_key_name="",
        tools=[native_echo],
        before_model_callback=before_model,
        after_model_callback=after_model,
        codex_runtime_config=CodexRuntimeConfig(
            integration_mode="native",
            responses_tool_format=tool_format,
            web_search="disabled" if tool_format == "functions" else None,
            session_root=str(tmp_path / "sessions"),
            workspace_root=str(tmp_path / "workspaces"),
            sandbox="read_only",
            reasoning_effort="minimal",
        ),
    )
    runner = Runner(agent=agent, app_name="native_test")
    await runner.short_term_memory.create_session(
        app_name="native_test", user_id="u", session_id="s"
    )
    events = []

    async def run(message):
        stream = runner.run_async(
            user_id="u",
            session_id="s",
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        )
        async with contextlib.aclosing(stream):
            async for event in stream:
                events.append(event)

    try:
        await asyncio.wait_for(run("first exact input"), 45)
        checkpoint = list((tmp_path / "sessions").glob("*/state.json"))
        assert len(checkpoint) == 1, "Native thread state must survive the invocation"
        first_state = json.loads(checkpoint[0].read_text())
        assert calls == ["native-result"], [
            [
                i
                for i in r.get("input", [])
                if i.get("type") in {"function_call", "function_call_output"}
            ]
            for r in backend.requests
        ]
        first_requests = len(backend.requests)
        assert first_requests == 2
        # This comes from the CLI's next request, not a fabricated ADK log.
        history = backend.requests[1]["input"]
        assert any(
            item.get("type") == "function_call_output"
            and item.get("call_id") == "call_native_1"
            and "native-result" in json.dumps(item)
            for item in history
        )
        if callback_mode == "short_circuit":
            await asyncio.wait_for(run("cached answer"), 45)
            assert len(backend.requests) == first_requests
        await asyncio.wait_for(run("second exact input"), 45)
        second_state = json.loads(checkpoint[0].read_text())
        if callback_mode in {"after", "short_circuit"}:
            assert second_state["thread_id"] != first_state["thread_id"]
            reason = (
                "after_model_content_changed"
                if callback_mode == "after"
                else "before_model_short_circuit"
            )
            text = "callback-final" if callback_mode == "after" else "callback-cache"
            assert second_state["migration_reason"] == reason
            assert text in json.dumps(backend.requests[-1]["input"])
        else:
            assert second_state["thread_id"] == first_state["thread_id"]
            assert second_state["migration_reason"] is None
        assert len(backend.requests) == first_requests + 1
        assert calls == ["native-result"]
        history = backend.requests[-1]["input"]
        if callback_mode not in {"after", "short_circuit"}:
            assert (
                sum(
                    item.get("call_id") == "call_native_1"
                    and item.get("type") == "function_call_output"
                    for item in history
                )
                == 1
            )
            assert "<conversation_history>" not in json.dumps(history)
        assert any("second exact input" in json.dumps(item) for item in history)
        if callback_mode == "before":
            assert "second exact input callback" in json.dumps(history)
        native_items = [
            e
            for e in events
            if (e.custom_metadata or {}).get("item_type") == "mcpToolCall"
        ]
        assert native_items, "Codex MCP lifecycle must reach ADK observers"
        adk_calls = [
            c
            for e in events
            if not e.partial
            for c in e.get_function_calls()
            if c.name == "native_echo"
        ]
        assert len(adk_calls) == 1
        assert adk_calls[0].id == "call_native_1"
        final_text = "callback-final" if callback_mode == "after" else "native-final"
        final_events = [
            e
            for e in events
            if e.content
            and not e.partial
            and any(p.text == final_text for p in e.content.parts)
        ]
        assert len(final_events) == 2
        assert [e.usage_metadata.total_token_count for e in final_events] == [36, 18]
    finally:
        await backend.stop()


@pytest.mark.codex_native
@pytest.mark.asyncio
@pytest.mark.parametrize("search_first", [False, True])
async def test_function_provider_keeps_native_apply_patch(tmp_path, search_first):
    from veadk import Agent, Runner
    from veadk.runtime.codex.config import CodexRuntimeConfig

    patch = "*** Begin Patch\n*** Add File: parity.txt\n+native patch result\n*** End Patch\n"

    class PatchBackend(_StubResponsesBackend):
        def _script(self, body):
            if search_first and len(self.requests) == 1:
                tool = next(
                    t for t in body["tools"] if "tool_search" in t.get("name", "")
                )
                return self._response(
                    body,
                    [
                        self._function_call(
                            tool["name"],
                            {"query": "patch", "limit": 1},
                            call_id="search-1",
                        )
                    ],
                )
            if not self._adk_call_sent:
                self._adk_call_sent = True
                tool = next(
                    (
                        t
                        for t in body.get("tools", [])
                        if "apply_patch" in t.get("description", "")
                        and "input" in t.get("parameters", {}).get("properties", {})
                    ),
                    None,
                )
                assert tool, "Native apply_patch must survive function-only adaptation"
                assert tool["type"] == "function"
                return self._response(
                    body,
                    [
                        self._function_call(
                            tool["name"], {"input": patch}, call_id="patch-1"
                        )
                    ],
                )
            return self._response(body, [self._message("patch-final")])

    backend = PatchBackend()
    url = await backend.start()
    workspace = tmp_path / "workspace"
    agent = Agent(
        name="native_patch",
        runtime="codex",
        # The CLI's built-in model catalog enables apply_patch for this
        # family. Unknown model names intentionally do not advertise it.
        model_name="gpt-5.4",
        model_api_base=url + "/v1",
        model_api_key="synthetic",
        model_api_key_name="",
        codex_runtime_config=CodexRuntimeConfig(
            integration_mode="native",
            responses_tool_format="functions",
            web_search="disabled",
            session_root=str(tmp_path / "sessions"),
            workspace_root=str(workspace),
            reuse_workspace=True,
            sandbox="workspace_write",
            reasoning_effort="minimal",
        ),
    )
    runner = Runner(agent=agent, app_name="native_test")
    await runner.short_term_memory.create_session(
        app_name="native_test", user_id="u", session_id="s"
    )
    events = []

    async def run():
        stream = runner.run_async(
            user_id="u",
            session_id="s",
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="create parity.txt using apply_patch")],
            ),
        )
        async with contextlib.aclosing(stream):
            async for event in stream:
                events.append(event)

    try:
        await asyncio.wait_for(run(), 45)
        assert (workspace / "parity.txt").exists(), {
            "schemas": [
                (
                    t.get("name"),
                    list(t.get("parameters", {}).get("properties", {})),
                    t.get("description", "")[:80],
                )
                for t in backend.requests[0].get("tools", [])
                if "patch" in t.get("name", "")
                or t.get("name", "").startswith("veadk_")
            ],
            "inputs": [
                [
                    i
                    for i in r.get("input", [])
                    if i.get("type") != "message" and i.get("role") is None
                ]
                for r in backend.requests
            ],
            "events": [e.custom_metadata for e in events],
        }
        assert (workspace / "parity.txt").read_text() == "native patch result\n"
        assert any(
            (e.custom_metadata or {}).get("item_type") == "fileChange" for e in events
        )
        assert len(backend.requests) == (3 if search_first else 2)
        if search_first:
            assert any(
                i.get("call_id") == "search-1"
                and i.get("type") == "function_call_output"
                for i in backend.requests[1]["input"]
            )
        assert any(
            i.get("type") == "function_call_output" and i.get("call_id") == "patch-1"
            for i in backend.requests[-1]["input"]
        )
    finally:
        await backend.stop()


@pytest.mark.codex_native
@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["confirmation", "authentication"])
async def test_native_cli_preserves_adk_confirmation(tmp_path, control):
    from fastapi.openapi.models import APIKey, APIKeyIn
    from google.adk.auth.auth_credential import AuthCredential, AuthCredentialTypes
    from google.adk.auth.auth_tool import AuthConfig
    from google.adk.tools.function_tool import FunctionTool
    from google.adk.tools.tool_context import ToolContext

    from veadk import Agent, Runner
    from veadk.runtime.codex.config import CodexRuntimeConfig

    calls = []
    auth_config = AuthConfig(
        auth_scheme=APIKey.model_validate(
            {"name": "x-test", "in": APIKeyIn.header, "type": "apiKey"}
        ),
        credential_key="synthetic-test",
    )

    def native_echo(value: str, tool_context: ToolContext) -> dict:
        """Synthetic side effect requiring confirmation."""
        if control == "authentication":
            credential = tool_context.get_auth_response(auth_config)
            if credential is None:
                tool_context.request_credential(auth_config)
                return {"status": "authentication_required"}
            assert credential.api_key == "synthetic-auth-only"
        calls.append(value)
        return {"value": value}

    backend = NativeBackend()
    url = await backend.start()
    agent = Agent(
        name="native_agent",
        runtime="codex",
        model_name="native-test",
        model_api_base=url + "/v1",
        model_api_key="synthetic",
        model_api_key_name="",
        tools=[
            FunctionTool(native_echo, require_confirmation=control == "confirmation")
        ],
        codex_runtime_config=CodexRuntimeConfig(
            integration_mode="native",
            session_root=str(tmp_path / "sessions"),
            workspace_root=str(tmp_path / "workspaces"),
            sandbox="read_only",
            reasoning_effort="minimal",
        ),
    )
    runner = Runner(agent=agent, app_name="native_test")
    await runner.short_term_memory.create_session(
        app_name="native_test", user_id="u", session_id="s"
    )

    async def run(message):
        result = []
        stream = runner.run_async(user_id="u", session_id="s", new_message=message)
        async with contextlib.aclosing(stream):
            async for event in stream:
                result.append(event)
        return result

    try:
        events = await asyncio.wait_for(
            run(types.Content(role="user", parts=[types.Part(text="perform action")])),
            45,
        )
        assert calls == []
        assert len(backend.requests) == 1, "Pending confirmation must stop model calls"
        confirmation = next(
            c
            for e in events
            for c in e.get_function_calls()
            if c.name
            == (
                "adk_request_confirmation"
                if control == "confirmation"
                else "adk_request_credential"
            )
        )
        response = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=confirmation.id,
                        name=confirmation.name,
                        response={"confirmed": True}
                        if control == "confirmation"
                        else AuthConfig(
                            auth_scheme=auth_config.auth_scheme,
                            exchanged_auth_credential=AuthCredential(
                                auth_type=AuthCredentialTypes.API_KEY,
                                api_key="synthetic-auth-only",
                            ),
                        ).model_dump(exclude_none=True, by_alias=True),
                    )
                )
            ],
        )
        second = await asyncio.wait_for(run(response), 45)
        assert calls == ["native-result"]
        assert len(backend.requests) == 2
        assert any(
            r.name == "native_echo" and r.response == {"value": "native-result"}
            for e in second
            for r in e.get_function_responses()
        )
        assert "native-result" in json.dumps(backend.requests[-1]["input"])
        assert "synthetic-auth-only" not in json.dumps(backend.requests)
    finally:
        await backend.stop()
