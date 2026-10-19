"""Exercise call budgets through HTTP, with real runners and synthetic models."""

import asyncio
import importlib
import json
import socket
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from veadk import Agent
from veadk.memory.short_term_memory import ShortTermMemory


def _payload(session_id="session", **kwargs):
    return {
        "app_name": "budget_test",
        "user_id": "user",
        "session_id": session_id,
        "streaming": True,
        "new_message": {"role": "user", "parts": [{"text": "query"}]},
        **kwargs,
    }


def _session_path(session_id="session"):
    return f"/apps/budget_test/users/user/sessions/{session_id}"


@pytest.fixture
def make_runtime(monkeypatch):
    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    monkeypatch.setattr(module, "has_a2a_registry_config", lambda agent: False)

    def build(limit, model=None):
        model_calls, tool_calls = [], []

        async def lookup() -> dict:
            """Return synthetic evidence."""
            tool_calls.append(True)
            return {"total": 13}

        class QueryModel(BaseLlm):
            model: str = "offline-call-budget"

            async def generate_content_async(self, llm_request, stream=False):
                model_calls.append(True)
                await asyncio.sleep(0)
                parts = llm_request.contents[-1].parts or []
                if any(part.function_response for part in parts):
                    part = types.Part(text="query complete")
                else:
                    part = types.Part(
                        function_call=types.FunctionCall(name="lookup", args={})
                    )
                yield LlmResponse(content=types.Content(role="model", parts=[part]))

        agent = Agent(name="budget_agent", model="offline", tools=[lookup])
        agent.model = model or QueryModel()
        memory = ShortTermMemory(session_service=InMemorySessionService())
        runtime = module.HarnessApp(agent, memory, "budget_test", max_llm_calls=limit)
        return runtime, model_calls, tool_calls

    return build


@pytest.mark.parametrize("route", ["/run", "/run_sse"])
@pytest.mark.parametrize("limit", [1, 2, None, 0, -1])
def test_delegated_http_enforces_actual_model_calls(make_runtime, route, limit):
    runtime, model_calls, tool_calls = make_runtime(limit)
    with TestClient(runtime.app, raise_server_exceptions=False) as client:
        assert client.post(_session_path(), json={}).status_code == 200
        for turn in range(2):
            response = client.post(route, json=_payload())
            assert len(model_calls) == (turn + 1) * (1 if limit == 1 else 2)
            assert len(tool_calls) == turn + 1
            if limit == 1:
                if route == "/run_sse":
                    assert response.status_code == 200
                    assert "LlmCallsLimitExceededError" in response.text
                else:
                    assert response.status_code == 500
                assert "query complete" not in response.text
            else:
                assert response.status_code == 200
                assert "query complete" in response.text
                assert '"error"' not in response.text
        history = client.get(_session_path()).json()
        assert (
            len(
                [
                    part
                    for event in history["events"]
                    for part in (event.get("content") or {}).get("parts", [])
                    if part.get("functionResponse") or part.get("function_response")
                ]
            )
            == 2
        )


@pytest.mark.parametrize("route", ["/run", "/run_sse"])
def test_limited_http_preserves_missing_session_404(make_runtime, route):
    runtime, model_calls, tool_calls = make_runtime(1)
    with TestClient(runtime.app) as client:
        response = client.post(route, json=_payload())
        assert response.status_code == 404
        assert not model_calls and not tool_calls
        assert client.get(_session_path()).status_code == 404


@pytest.mark.parametrize("route", ["/run", "/run_sse"])
def test_limited_http_preserves_metadata_and_state(make_runtime, route):
    runtime, _, _ = make_runtime(2)
    with TestClient(runtime.app) as client:
        assert client.post(_session_path(), json={}).status_code == 200
        response = client.post(
            route,
            json=_payload(
                custom_metadata={"fixture": "budget"},
                state_delta={"fixture": 13},
            ),
        )
        assert response.status_code == 200
        events = (
            response.json()
            if route == "/run"
            else [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
        )
        assert events and all(
            event.get("customMetadata", event.get("custom_metadata"))
            == {"fixture": "budget"}
            for event in events
        )
        assert client.get(_session_path()).json()["state"]["fixture"] == 13


def test_explicit_harness_limit_stays_request_scoped(make_runtime):
    runtime, model_calls, _ = make_runtime(1)
    with TestClient(runtime.app) as client:
        assert client.post(_session_path(), json={}).status_code == 200
        overridden = client.post(
            "/run_sse", json=_payload(harness={"max_llm_calls": 2})
        )
        assert overridden.status_code == 200
        assert "query complete" in overridden.text
        assert len(model_calls) == 2
        default = client.post("/run_sse", json=_payload())
        assert "LlmCallsLimitExceededError" in default.text
        assert len(model_calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/run", "/run_sse"])
async def test_concurrent_sessions_have_independent_budgets(make_runtime, route):
    runtime, model_calls, tool_calls = make_runtime(2)
    transport = httpx.ASGITransport(app=runtime.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for session in ("first", "second"):
            assert (
                await client.post(_session_path(session), json={})
            ).status_code == 200
        responses = await asyncio.gather(
            *[
                client.post(route, json=_payload(session))
                for session in ("first", "second")
            ]
        )
        assert all(
            response.status_code == 200 and "query complete" in response.text
            for response in responses
        )
        assert len(model_calls) == 4 and len(tool_calls) == 2


@asynccontextmanager
async def _serve(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=1,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError("HTTP server exited before startup")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 5)
        finally:
            listener.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route,partial", [("/run", False), ("/run_sse", False), ("/run_sse", True)]
)
async def test_disconnect_cleans_model_and_next_turn_succeeds(
    make_runtime, route, partial
):
    started, closed = asyncio.Event(), asyncio.Event()

    class WaitingModel(BaseLlm):
        model: str = "offline-cancellation-budget"

        async def generate_content_async(self, llm_request, stream=False):
            if llm_request.contents[-1].parts[0].text == "continue":
                yield LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="ready again")],
                    )
                )
                return
            started.set()
            try:
                if partial:
                    yield LlmResponse(
                        partial=True,
                        content=types.Content(
                            role="model",
                            parts=[types.Part(text="partial response")],
                        ),
                    )
                await asyncio.Event().wait()
            finally:
                closed.set()

    runtime, _, _ = make_runtime(1, WaitingModel())
    async with _serve(runtime.app) as base:
        async with httpx.AsyncClient(base_url=base, timeout=5) as client:
            assert (await client.post(_session_path(), json={})).status_code == 200
            if route == "/run":
                request = asyncio.create_task(client.post(route, json=_payload()))
                try:
                    await asyncio.wait_for(started.wait(), 3)
                finally:
                    request.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await request
            else:
                async with client.stream("POST", route, json=_payload()) as response:
                    assert response.status_code == 200
                    await asyncio.wait_for(started.wait(), 3)
                    if partial:
                        async for line in response.aiter_lines():
                            if "partial response" in line:
                                break
            await asyncio.wait_for(closed.wait(), 3)
            response = await client.post(
                route,
                json=_payload(
                    new_message={
                        "role": "user",
                        "parts": [{"text": "continue"}],
                    }
                ),
            )
            assert response.status_code == 200
            assert "ready again" in response.text
            assert '"error"' not in response.text
