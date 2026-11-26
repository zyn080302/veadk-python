"""Real Codex + MCP + Runner, scripted provider, oversized history and recovery."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from test_codex_runtime_smoke import _StubResponsesBackend, _skip_reason


@pytest.mark.codex_smoke
@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["direct", "shim"])
async def test_real_codex_oversized_restart_reader_followup_and_recovery(
    monkeypatch, tmp_path, transport
):
    if os.environ.get("CODEX_RUN_SMOKE") != "1":
        pytest.skip("set CODEX_RUN_SMOKE=1 for real process")
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    from google.adk.events.event import Event
    from google.genai import types
    from veadk import Agent, Runner
    from veadk.memory.short_term_memory import ShortTermMemory
    from litellm.exceptions import BadRequestError
    from veadk.runtime.codex.config import CodexRuntimeConfig
    from veadk.runtime.codex.proxy import _synth_sse
    from veadk.runtime.codex import runtime as runtime_module

    monkeypatch.setenv("OBSERVABILITY_OPENTELEMETRY_TRACE_CONTENT", "false")
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(runtime_module, "_SESSION_WORKSPACE_ROOT", str(workspace_root))
    backend = _StubResponsesBackend()
    app = FastAPI()
    phase = "primer"
    calls = []
    requested = set()
    read_confirmed = set()
    final = "SYNTH-73 confirms supervised approval is supported."
    current = "Which approval mode does SYNTH-73 support? Cite the ticket."

    @app.post("/v1/responses")
    async def responses(request: Request):
        body = await request.json()
        calls.append(phase)
        if phase == "failure":
            return JSONResponse(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "message": "synthetic failure",
                    }
                },
                status_code=400,
            )
        if phase != "primer":
            serial = json.dumps(body.get("input"), ensure_ascii=False)
            if phase not in requested:
                assert current in serial
                assert (
                    "supervised approval is supported" not in serial
                    or phase != "restart"
                )
                refs = re.findall(r"context_[0-9a-f]{24}", serial)
                assert refs, "No current invocation context reference reached the model"
                output = [
                    backend._function_call(
                        "_veadk_read_context",
                        {
                            "reference": refs[-1],
                            "offset": 0,
                            "length": 100,
                            "query": "SYNTH-73:",
                        },
                        call_id="read-" + phase,
                    )
                ]
                if transport == "direct":
                    output[0]["namespace"] = "mcp__veadk"
                requested.add(phase)
            else:
                matching = [
                    x
                    for x in (body.get("input") or [])
                    if isinstance(x, dict)
                    and x.get("type") == "function_call_output"
                    and x.get("call_id") == "read-" + phase
                ]
                assert matching and "supervised approval is supported" in json.dumps(
                    matching
                )
                read_confirmed.add(phase)
                output = [backend._message(final)]
                output[0]["phase"] = "final_answer"
        else:
            output = [backend._message("Ready for evidence.")]
            output[0]["phase"] = "final_answer"
        response = backend._response(body, output)
        if not body.get("stream"):
            return JSONResponse(response)
        return StreamingResponse(_synth_sse(response), media_type="text/event-stream")

    backend._app = app
    url = await backend.start()
    agent = Agent(
        name="context_smoke",
        instruction="Use authorized evidence.",
        runtime="codex",
        model_name="scripted-model",
        model_api_base=url + "/v1",
        model_api_key="local-synthetic-key",
        model_api_key_name="",
        output_key="answer",
        codex_runtime_config=CodexRuntimeConfig(
            model_transport=transport,
            shell_enabled=False,
            sandbox="read_only",
            network_access=False,
            reasoning_effort="minimal",
            tool_timeout_seconds=10,
            turn_timeout_seconds=25,
        ),
    )

    def new_runner():
        memory = ShortTermMemory(
            backend="sqlite", local_database_path=str(tmp_path / "session.db")
        )
        return Runner(agent=agent, app_name="context_smoke", short_term_memory=memory)

    runner = new_runner()
    session_id = "context-" + uuid.uuid4().hex
    await runner.short_term_memory.create_session(
        app_name="context_smoke", user_id="test", session_id=session_id
    )
    workspace_root = Path(runtime_module._SESSION_WORKSPACE_ROOT)
    before = set(workspace_root.iterdir())

    def visible(events):
        return [
            p.text
            for e in events
            if not e.partial and e.author == agent.name and e.content
            for p in e.content.parts
            if p.text and not p.thought
        ]

    async def drive():
        stream = runner.run_async(
            user_id="test",
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=current)]),
        )
        async with contextlib.aclosing(stream):
            return [event async for event in stream]

    try:
        async with asyncio.timeout(180):
            primer = await drive()
            assert visible(primer) == ["Ready for evidence."]
            session = await runner.session_service.get_session(
                app_name="context_smoke", user_id="test", session_id=session_id
            )
            source = (
                "unrelated old material " * 30000
                + "SYNTH-73: supervised approval is supported. "
                + "other old material " * 40000
            )
            await runner.session_service.append_event(
                session=session,
                event=Event(
                    author=agent.name,
                    invocation_id="seed",
                    content=types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name="knowledge_search", response={"text": source}
                                )
                            )
                        ],
                    ),
                ),
            )
            agent.instruction = "Use authorized evidence. Include the ticket citation."
            for phase_value in ["restart", "followup", "failure", "recovery"]:
                phase = phase_value
                if phase in {"followup", "recovery"}:
                    await runner.session_service.db_engine.dispose()
                    runner = new_runner()
                if phase == "failure" and transport == "shim":
                    with pytest.raises(BadRequestError, match="synthetic failure"):
                        await drive()
                elif phase == "failure":
                    events = await drive()
                    assert any(e.error_code for e in events)
                    assert visible(events) == []
                else:
                    events = await drive()
                    assert not any(e.error_code for e in events)
                    assert visible(events) == [final]
                    assert phase in read_confirmed
                session = await runner.session_service.get_session(
                    app_name="context_smoke", user_id="test", session_id=session_id
                )
                assert session.state["answer"] == final
            assert visible(session.events) == [
                "Ready for evidence.",
                final,
                final,
                final,
            ]
            assert calls == [
                "primer",
                "restart",
                "restart",
                "followup",
                "followup",
                *(["failure"] * (3 if transport == "shim" else 1)),
                "recovery",
                "recovery",
            ]
    finally:
        await backend.stop()
        await runner.session_service.db_engine.dispose()
        for path in set(workspace_root.iterdir()) - before:
            shutil.rmtree(path, ignore_errors=True)
