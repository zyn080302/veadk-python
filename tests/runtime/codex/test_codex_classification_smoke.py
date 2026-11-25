"""Real Codex process, local scripted Responses server, Runner and history."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from test_codex_runtime_smoke import _StubResponsesBackend, _codex_homes, _skip_reason


@pytest.mark.codex_smoke
@pytest.mark.asyncio
async def test_real_codex_phase_thought_history_and_recovery(monkeypatch):
    if os.getenv("CODEX_RUN_SMOKE") != "1":
        pytest.skip("set CODEX_RUN_SMOKE=1 for real local Codex process")
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    from google.genai import types

    from veadk import Agent, Runner
    from veadk.runtime.codex import runtime as runtime_module
    from veadk.runtime.codex.config import CodexRuntimeConfig
    from veadk.runtime.codex.proxy import _synth_sse

    monkeypatch.setenv("OBSERVABILITY_OPENTELEMETRY_TRACE_CONTENT", "false")
    backend = _StubResponsesBackend()
    app = FastAPI()
    mode = "first"
    observed_final_delta = asyncio.Event()
    observed_modes = []

    @app.post("/v1/responses")
    async def responses(request: Request):
        body = await request.json()
        observed_modes.append(mode)
        if mode == "failure":
            return JSONResponse(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "message": "synthetic rejection",
                    }
                },
                status_code=400,
            )
        answer = f"answer-{mode}"
        progress = backend._message(f"progress-{mode}")
        final = backend._message(answer)
        if mode == "followup":
            final["content"] = [
                {"type": "output_text", "text": text, "annotations": []}
                for text in ("answer-", "followup")
            ]
        if mode != "followup":
            progress["phase"] = "commentary"
            final["phase"] = "final_answer"
        output = [
            {
                "type": "reasoning",
                "id": "reasoning-" + mode,
                "summary": [
                    {"type": "summary_text", "text": "synthetic reasoning marker"}
                ],
            },
            progress,
            final,
        ]
        response = backend._response(body, output)

        async def stream():
            async for chunk in _synth_sse(response):
                yield chunk
                # The real process must deliver final deltas before EOF.
                if mode == "first" and b"response.output_text.delta" in chunk:
                    data = json.loads(chunk.decode().split("data: ", 1)[1])
                    if data.get("delta") == answer:
                        await asyncio.wait_for(observed_final_delta.wait(), 10)

        return StreamingResponse(stream(), media_type="text/event-stream")

    backend._app = app
    url = await backend.start()
    callbacks = []

    def after_model(callback_context, llm_response):
        callbacks.append(
            [
                p.text
                for p in (llm_response.content.parts if llm_response.content else [])
                if p.text and not p.thought
            ]
        )

    agent = Agent(
        name="classification_smoke",
        instruction="Answer the synthetic request.",
        runtime="codex",
        model_name="scripted-model",
        model_api_base=url + "/v1",
        model_api_key="local-synthetic-key",
        model_api_key_name="",
        after_model_callback=after_model,
        output_key="answer",
        codex_runtime_config=CodexRuntimeConfig(
            model_transport="direct",
            sandbox="read_only",
            network_access=False,
            turn_timeout_seconds=25,
            reasoning_effort="minimal",
        ),
    )
    runner = Runner(agent=agent, app_name="classification_smoke")
    session_id = "classification-" + uuid.uuid4().hex
    await runner.short_term_memory.create_session(
        app_name="classification_smoke",
        user_id="test",
        session_id=session_id,
    )
    before_homes = _codex_homes(Path(tempfile.gettempdir()))
    workspace_root = Path(runtime_module._SESSION_WORKSPACE_ROOT)
    before_workspaces = set(workspace_root.iterdir())

    def visible(events):
        return [
            p.text
            for e in events
            for p in (e.content.parts if e.content else [])
            if p.text and not p.thought and e.author == agent.name
        ]

    async def drive():
        events = []
        stream = runner.run_async(
            user_id="test",
            session_id=session_id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=f"request-{mode}")]
            ),
        )
        async with contextlib.aclosing(stream):
            async for event in stream:
                events.append(event)
                if event.partial and "answer-first" in visible([event]):
                    observed_final_delta.set()
        return events

    try:
        for current in ("first", "followup", "failure", "recovery"):
            mode = current
            if mode == "failure":
                failed = await asyncio.wait_for(drive(), 35)
                assert any(
                    e.error_code and "synthetic rejection" in (e.error_message or "")
                    for e in failed
                )
                assert visible(failed) == []
                failed_session = await runner.session_service.get_session(
                    app_name="classification_smoke",
                    user_id="test",
                    session_id=session_id,
                )
                assert failed_session.state["answer"] == "answer-followup"
                continue
            events = await asyncio.wait_for(drive(), 35)
            assert visible([e for e in events if not e.partial]) == [f"answer-{mode}"]
            assert not any(t.startswith("progress-") for t in visible(events))
            assert any(p.thought for e in events if e.content for p in e.content.parts)
            assert callbacks[-1] == [f"answer-{mode}"]
            final = [e for e in events if not e.partial and visible([e])][-1]
            assert final.custom_metadata["phase"] == (
                None if mode == "followup" else "final_answer"
            )
            session = await runner.session_service.get_session(
                app_name="classification_smoke",
                user_id="test",
                session_id=session_id,
            )
            assert session.state["answer"] == f"answer-{mode}"
            assert not any(t.startswith("progress-") for t in visible(session.events))
            if mode == "first":
                assert observed_final_delta.is_set()
                progress_events = [
                    e
                    for e in events
                    if (e.custom_metadata or {}).get("phase") == "commentary"
                ]
                assert progress_events and all(e.partial for e in progress_events)
                assert all(e.content is None for e in progress_events)
        assert observed_modes == ["first", "followup", "failure", "recovery"]
        assert visible(session.events) == [
            "answer-first",
            "answer-followup",
            "answer-recovery",
        ]
    finally:
        await backend.stop()
        for path in set(workspace_root.iterdir()) - before_workspaces:
            shutil.rmtree(path, ignore_errors=True)
    assert _codex_homes(Path(tempfile.gettempdir())) == before_homes
