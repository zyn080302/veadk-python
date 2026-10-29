"""Regressions for final phase, terminal status and executor teardown."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from google.adk.sessions.session import Session
from google.genai import types
from mcp import types as mcp_types
from openai_codex.generated.v2_all import (
    ItemCompletedNotification,
    TurnCompletedNotification,
)

from test_codex_runtime_sdk import _Agent, _Context, _FakeShim
from veadk.runtime.codex import mcp_bridge, runtime, translate
from veadk.runtime.codex.proxy import _synth_sse


def _message(phase, text, item_id="answer"):
    return ItemCompletedNotification.model_validate(
        {
            "threadId": "thread-offline",
            "turnId": "turn-offline",
            "completedAtMs": 1,
            "item": {
                "type": "agentMessage",
                "id": item_id,
                "text": text,
                "phase": phase,
            },
        }
    )


@pytest.mark.parametrize("phase", ["commentary", "partial_answer"])
def test_narration_preserves_phase_and_is_partial(phase):
    # partial_answer is a forward-compatible wire value, not in SDK 0.163's enum.
    note = ItemCompletedNotification.model_construct(
        item={
            "type": "agentMessage",
            "id": "progress",
            "text": "progress",
            "phase": phase,
        }
    )
    events = translate.notification_to_events(note, "agent", "invocation")
    assert events
    assert events[0].custom_metadata["phase"] == phase
    assert events[0].partial
    assert not translate.is_codex_final_text_event(events[0])


async def _run(monkeypatch, status="completed", messages=None, *, fallback=False):
    statuses, events, after_responses = [], [], []
    messages = messages or [("final_answer", "final")]

    class Turn:
        id = "turn-offline"

        async def interrupt(self):
            return None

        def stream(self):
            async def stream():
                for i, (phase, text) in enumerate(messages):
                    yield SimpleNamespace(
                        method="item/completed", payload=_message(phase, text, str(i))
                    )
                if status != "missing":
                    yield SimpleNamespace(
                        method="turn/completed",
                        payload=TurnCompletedNotification.model_validate(
                            {
                                "threadId": "thread-offline",
                                "turn": {
                                    "id": self.id,
                                    "status": status,
                                    "items": [],
                                    "error": {"message": "synthetic failure"}
                                    if status == "failed"
                                    else None,
                                },
                            }
                        ),
                    )

            return stream()

    class Codex:
        def __init__(self, *, config):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def thread_start(self, **kwargs):
            class Thread:
                async def turn(self, *args, **kwargs):
                    return Turn()

            return Thread()

    async def get_shim(*args):
        return _FakeShim()

    original_after = runtime.run_after_model_callbacks

    async def after(agent, ctx, response, event):
        after_responses.append(response)
        return await original_after(agent, ctx, response, event)

    if fallback:
        from google.adk.models.llm_response import LlmResponse

        async def on_error(*args):
            return LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="recovery")])
            )

        monkeypatch.setattr(runtime, "run_on_model_error_callbacks", on_error)
    monkeypatch.setattr(runtime, "run_after_model_callbacks", after)
    monkeypatch.setattr(runtime, "AsyncCodex", Codex)
    monkeypatch.setattr(runtime, "get_shim", get_shim)
    monkeypatch.setattr(
        runtime.codex_metrics, "record_turn", lambda s, *a: statuses.append(s)
    )
    agent = _Agent()
    ctx = _Context(
        invocation_id="invocation",
        agent=agent,
        branch=None,
        isolation_scope=None,
        user_content=types.Content(role="user", parts=[types.Part(text="question")]),
        session=Session(
            id="session", app_name="app", user_id="user", state={}, events=[]
        ),
    )
    error = None
    try:
        async for event in runtime.CodexRuntime().run_async(agent, ctx):
            events.append(event)
    except Exception as exc:
        error = exc
    return events, statuses, after_responses, error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "messages, expected",
    [
        ([("commentary", "progress"), ("final_answer", "final")], "final"),
        ([(None, "legacy preamble"), (None, "legacy answer")], "legacy answer"),
        ([(None, "legacy"), ("final_answer", "final"), (None, "late legacy")], "final"),
        ([("final_answer", "first"), ("final_answer", "last")], "last"),
    ],
)
async def test_runtime_selects_final_with_legacy_fallback(
    monkeypatch, messages, expected
):
    from openai_codex._run import _final_assistant_response_from_items

    items = [
        _message(phase, text, str(i)).item for i, (phase, text) in enumerate(messages)
    ]
    assert _final_assistant_response_from_items(items) == expected
    events, statuses, responses, error = await _run(monkeypatch, messages=messages)
    assert error is None
    assert statuses == ["completed"]
    assert len(responses) == 1
    assert [p.text for p in responses[0].content.parts] == [expected]
    finals = [
        e for e in events if e.is_final_response() and e.content and not e.error_code
    ]
    assert len(finals) == 1
    assert [p.text for p in finals[0].content.parts] == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, metric",
    [("failed", "failed"), ("interrupted", "cancelled"), ("missing", "failed")],
)
@pytest.mark.parametrize("fallback", [False, True])
async def test_non_success_turn_cannot_deliver_success(
    monkeypatch, status, metric, fallback
):
    events, statuses, responses, error = await _run(
        monkeypatch, status, fallback=fallback
    )
    assert statuses == [metric]
    assert responses == []
    assert not any(
        e.is_final_response() and e.content and not e.error_code for e in events
    )
    if fallback:
        assert error is None
        assert any(e.error_code for e in events)
    else:
        assert error is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["completed", "failed", "incomplete", None, "in_progress", "unsupported"]
)
async def test_synthesized_sse_preserves_terminal_status(status):
    response = {
        "id": "offline-response",
        "status": status,
        "output": [
            {
                "id": "message",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "partial", "annotations": []}
                ],
            }
        ],
        "error": {"code": "synthetic", "message": "synthetic failure"},
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    original = json.loads(json.dumps(response))
    frames = [
        json.loads(f.partition(b"\ndata: ")[2]) async for f in _synth_sse(response)
    ]
    expected = status if status in {"completed", "failed", "incomplete"} else "failed"
    assert frames[-1]["type"] == f"response.{expected}"
    assert frames[-1]["response"]["status"] == expected
    assert (
        frames[-1]["response"]["incomplete_details"] == original["incomplete_details"]
    )
    if status == "failed":
        assert frames[-1]["response"]["error"] == original["error"]
    assert any(f["type"] == "response.output_text.delta" for f in frames)
    assert [f["sequence_number"] for f in frames] == list(range(len(frames)))
    assert response == original


@pytest.mark.asyncio
@pytest.mark.parametrize("recancel", [False, True])
@pytest.mark.parametrize("guarded", [False, True])
async def test_bridge_close_waits_for_finally_and_revokes_admission(recancel, guarded):
    bridge = mcp_bridge.McpBridge()
    entered, cleaning, finish, done = (asyncio.Event() for _ in range(4))
    resource = {"closed": False}
    observations = []

    async def execute(args, call_id):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await finish.wait()
            observations.append(resource["closed"])
            done.set()

    specs = [{"name": "offline", "parameters": {"type": "object"}}]
    process_token = bridge.register_process(specs) if guarded else None
    token = bridge.register_turn(specs, {"offline": execute}, token=process_token)
    if guarded:
        bridge.activate_turn(token, "thread-fixture", "turn-fixture")
    state = bridge._lookup(token)
    slot = mcp_bridge._CallSlot()
    state.slots["request"] = slot
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="offline", arguments={}),
    )
    call = asyncio.create_task(bridge._call_tool(state, slot, req))
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        closing = asyncio.create_task(bridge.close_turn(token))
        await asyncio.wait_for(cleaning.wait(), 2)
        assert bridge._lookup(token) is None
        assert not closing.done()
        if recancel:
            slot.cancel()
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
        finish.set()
        await asyncio.gather(closing, return_exceptions=True)
        resource["closed"] = True
        assert done.is_set()
        assert observations == [False]
        rejected = await bridge._call_tool(state, None, req)
        assert rejected.root.isError
    finally:
        finish.set()
        slot.cancel()
        await asyncio.gather(
            call, *([closing] if closing else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_bridge_close_waits_for_executor_on_another_loop():
    bridge = mcp_bridge.McpBridge()
    entered, cleaning, finished = (threading.Event() for _ in range(3))
    worker_loop = asyncio.new_event_loop()
    worker = threading.Thread(target=worker_loop.run_forever)
    worker.start()
    release = asyncio.Event()

    async def execute(args, call_id):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await release.wait()
            finished.set()

    token = bridge.register_turn(
        [{"name": "offline", "parameters": {"type": "object"}}],
        {"offline": execute},
    )
    state = bridge._lookup(token)
    slot = mcp_bridge._CallSlot()
    state.slots["request"] = slot
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="offline", arguments={}),
    )
    call = asyncio.run_coroutine_threadsafe(
        bridge._call_tool(state, slot, req), worker_loop
    )
    closing = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        closing = asyncio.create_task(bridge.close_turn(token))
        assert await asyncio.to_thread(cleaning.wait, 2)
        assert not closing.done()
        assert not finished.is_set()
        assert bridge._lookup(token) is None
        worker_loop.call_soon_threadsafe(release.set)
        await asyncio.wait_for(closing, 2)
        assert finished.is_set()
        await asyncio.wrap_future(call)
    finally:
        worker_loop.call_soon_threadsafe(release.set)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        await asyncio.gather(asyncio.wrap_future(call), return_exceptions=True)
        worker_loop.call_soon_threadsafe(worker_loop.stop)
        await asyncio.to_thread(worker.join, 2)
        worker_loop.close()


@pytest.mark.codex_smoke
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "messages, expected",
    [
        ([("commentary", "progress"), ("final_answer", "final")], "final"),
        ([(None, "preamble"), (None, "answer")], "answer"),
        ([(None, "legacy"), ("final_answer", "final"), (None, "late legacy")], "final"),
        ([("final_answer", "first"), ("final_answer", "last")], "last"),
    ],
)
async def test_real_cli_final_matches_official_collector(
    tmp_path, monkeypatch, messages, expected
):
    """Exercise full Runner delivery against a local Responses fixture."""
    import os
    from contextlib import aclosing, asynccontextmanager
    from openai_codex._run import _final_assistant_response_from_items
    from tests.runtime.codex.test_codex_mcp_bridge import _StubModel
    from tests.runtime.codex.test_codex_runtime_smoke import _skip_reason
    from veadk import Agent, Runner
    from veadk.runtime.codex.config import CodexRuntimeConfig
    from veadk.runtime.codex.mcp_bridge import shutdown_bridge
    from veadk.runtime.codex.provider_extension import CodexProviderEndpoint

    if os.getenv("CODEX_RUN_SMOKE") != "1":
        pytest.skip("set CODEX_RUN_SMOKE=1 to run the real CLI")
    if reason := _skip_reason():
        pytest.skip(reason)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("VEADK_CODEX_THREAD_MODE", "ephemeral")
    items = [
        _message(phase, text, str(i)).item for i, (phase, text) in enumerate(messages)
    ]
    assert _final_assistant_response_from_items(items) == expected

    class Model(_StubModel):
        def _script(self, body):
            return [
                {
                    "type": "message",
                    "id": f"msg_{i}",
                    "role": "assistant",
                    "status": "completed",
                    "phase": phase,
                    "content": [
                        {"type": "output_text", "text": text, "annotations": []}
                    ],
                }
                for i, (phase, text) in enumerate(messages)
            ]

    model = Model("unused", {})
    model_url = await model.start()

    @asynccontextmanager
    async def factory(agent, ctx):
        yield CodexProviderEndpoint(
            model_url, "offline-fixture", handles_extra_body=True
        )

    agent = Agent(
        name="terminal_smoke",
        runtime="codex",
        model_name="fixture-model",
        model_api_base="https://unused.invalid/v1",
        model_api_key="unused-fixture",
        model_api_key_name="",
        codex_runtime_config=CodexRuntimeConfig(
            provider_factory=factory,
            shell_enabled=False,
            sandbox="read_only",
            workspace_root=str(tmp_path / "workspace"),
            thread_mode="ephemeral",
            turn_timeout_seconds=60,
        ),
    )
    runner = Runner(agent=agent, app_name="terminal_smoke")
    await runner.short_term_memory.create_session(
        app_name="terminal_smoke", user_id="fixture", session_id="fixture-session"
    )
    try:
        async with asyncio.timeout(60):
            async with aclosing(
                runner.run_async(
                    user_id="fixture",
                    session_id="fixture-session",
                    new_message=types.Content(
                        role="user", parts=[types.Part(text="Answer the fixture")]
                    ),
                )
            ) as stream:
                events = [event async for event in stream]
    finally:
        await shutdown_bridge()
        await model.stop()
    finals = [
        event
        for event in events
        if event.is_final_response() and event.content and not event.error_code
    ]
    assert len(finals) == 1
    assert [part.text for part in finals[0].content.parts if part.text] == [expected]
    assert model.requests
    assert not any(
        tool.get("name") in {"shell", "exec_command"}
        for tool in model.requests[0].get("tools", [])
    )


@pytest.mark.asyncio
async def test_pooled_finish_timeout_still_waits_for_cleanup_on_close(monkeypatch):
    """A failed parking attempt must retain pending executor ownership."""
    monkeypatch.setattr(mcp_bridge, "_STOP_TIMEOUT_SECONDS", 0.01)
    bridge = mcp_bridge.McpBridge()
    specs = [{"name": "offline", "parameters": {"type": "object"}}]
    token = bridge.register_process(specs)
    started, cleaning, release, done = (asyncio.Event() for _ in range(4))

    async def execute(args, call_id):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await release.wait()
            done.set()

    bridge.register_turn(specs, {"offline": execute}, token=token)
    bridge.activate_turn(token, "fixture-thread", "fixture-turn")
    state = bridge._lookup(token)
    slot = mcp_bridge._CallSlot()
    state.slots["request"] = slot
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="offline", arguments={}),
    )
    call = asyncio.create_task(bridge._call_tool(state, slot, req))
    closing = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert not await bridge.finish_turn(token)
        assert cleaning.is_set()
        assert bridge._lookup(token) is None
        closing = asyncio.create_task(bridge.close_turn(token))
        await asyncio.sleep(0.01)
        assert not closing.done(), (
            "close released resources while executor cleanup was pending"
        )
        release.set()
        await asyncio.wait_for(closing, 2)
        assert done.is_set()
    finally:
        release.set()
        await asyncio.gather(
            call, *([closing] if closing else []), return_exceptions=True
        )
        bridge.release_process(token)
