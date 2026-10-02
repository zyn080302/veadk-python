"""Real shim error transport and recovery state; synthetic provider only."""

from copy import deepcopy

import httpx
import pytest
from openai import APIStatusError

from veadk.runtime.codex import proxy
from tests.runtime.codex.test_codex_live_stream import call, events, frame, response


def provider_error(status):
    return APIStatusError(
        "synthetic provider failure",
        response=httpx.Response(status, request=httpx.Request("POST", "http://test")),
        body=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", [429, 503])
async def test_transient_retry_preserves_tools_and_clears_only_recovered_error(
    monkeypatch, stream, status
):
    requests, executions = [], []
    failure = provider_error(status)

    async def query(args, call_id):
        executions.append(call_id)
        return '{"count":73,"scope":"test"}'

    async def backend(**kwargs):
        requests.append(deepcopy(kwargs["input"]))
        if len(requests) == 2:
            raise failure
        result = response(output=[call("query")]) if len(requests) == 1 else response()
        return events(result) if stream else result

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("http://test", "synthetic")
    token = shim.register_turn(
        [{"type": "function", "name": "query", "parameters": {}}], {"query": query}
    )
    body = {
        "model": "synthetic",
        "stream": stream,
        "input": [{"role": "user", "content": "original"}],
    }
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=shim._app), base_url="http://shim"
        ) as client:

            async def attempt():
                return await client.post(
                    "/v1/responses",
                    json=body,
                    headers={"Authorization": "Bearer " + token},
                )

            first = await attempt()
            assert shim.turn_error(token) is failure
            if stream:
                failed = [
                    frame(row.encode()) for row in first.text.split("\n\n") if row
                ][-1]
                assert failed["type"] == "response.failed"
                assert failed["response"]["error"]["code"] != "invalid_prompt"
            else:
                assert first.status_code == status
            second = await attempt()
            assert second.status_code == 200
            assert shim.turn_error(token) is None
        assert len(requests) == 3
        assert executions == ["call-1"]
        assert requests[1] == requests[2]
        assert requests[-1][-1]["output"] == '{"count":73,"scope":"test"}'
    finally:
        shim.unregister_turn(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_nonretryable_backend_failure_is_never_erased_by_later_success(
    monkeypatch, status
):
    failure = provider_error(status)
    count = 0

    async def backend(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise failure
        return events(response())

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("http://test", "synthetic")
    token = shim.register_turn([], {})
    from tests.runtime.codex.test_codex_live_stream import post

    try:
        failed = await post(shim, token)
        assert failed[-1]["response"]["error"]["code"] == "invalid_prompt"
        await post(shim, token)
        assert shim.turn_error(token) is failure
    finally:
        shim.unregister_turn(token)


def test_recovery_is_scoped_and_cannot_erase_newer_or_hard_errors():
    state = proxy.TurnToolState()
    first, newer = provider_error(429), provider_error(503)
    state.record_backend_error(first, "request-a")
    state.acknowledge_backend_recovery("request-b", first)
    assert state.error is first
    state.record_backend_error(newer, "request-a")
    state.acknowledge_backend_recovery("request-a", first)
    assert state.error is newer
    hard = RuntimeError("synthetic budget exhausted")
    state.record_error(hard)
    state.acknowledge_backend_recovery("request-a", newer)
    assert state.backend_error("request-a") is None
    assert state.error is hard


def test_unresolved_errors_are_bounded_without_forgetting_failures():
    state = proxy.TurnToolState()
    failure = provider_error(503)
    for index in range(64):
        state.record_backend_error(failure, str(index))
    state.record_backend_error(provider_error(429), "overflow")
    assert state.backend_error("overflow") is None
    assert isinstance(state.error, RuntimeError)
    for index in range(64):
        assert state.backend_error(str(index)) is failure
        state.acknowledge_backend_recovery(str(index), failure)
    assert isinstance(state.error, RuntimeError)


@pytest.mark.asyncio
@pytest.mark.parametrize("replay", [True, False])
async def test_history_owner_only_controls_cross_request_replay(monkeypatch, replay):
    requests, executions = [], []

    async def query(args, call_id):
        executions.append(call_id)
        return '{"count":73}'

    async def backend(**kwargs):
        requests.append(deepcopy(kwargs["input"]))
        return response(output=[call("query")]) if len(requests) == 1 else response()

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("http://test", "synthetic")
    token = shim.register_turn(
        [{"type": "function", "name": "query", "parameters": {}}],
        {"query": query},
        **({} if replay else {"replay_tool_history": False}),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=shim._app), base_url="http://shim"
        ) as client:
            for _ in range(2):
                result = await client.post(
                    "/v1/responses",
                    json={
                        "model": "synthetic",
                        "input": [{"role": "user", "content": "go"}],
                    },
                    headers={"Authorization": "Bearer " + token},
                )
                assert result.status_code == 200
        assert len(requests) == 3
        assert executions == ["call-1"]
        assert requests[1][-1]["output"] == '{"count":73}'
        assert requests[2] == (requests[1] if replay else requests[0])
    finally:
        shim.unregister_turn(token)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("local"),
        proxy.TurnResponseError(
            status_code=503, error_type="tool_execution_error", message="local"
        ),
    ],
)
def test_local_errors_are_not_provider_retries(error):
    assert not proxy._is_retryable_backend_error(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        {"instructions": "different"},
        {"model": "another"},
        {"input": "another"},
        {"metadata": {"scope": "another"}},
    ],
)
async def test_recovery_requires_same_request_identity(monkeypatch, changed):
    failure = provider_error(503)
    count = 0

    async def backend(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise failure
        return response()

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("http://test", "synthetic")
    token = shim.register_turn([], {})
    body = {"model": "synthetic", "input": "original"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=shim._app), base_url="http://shim"
        ) as client:

            async def attempt(payload):
                return await client.post(
                    "/v1/responses",
                    json=payload,
                    headers={"Authorization": "Bearer " + token},
                )

            assert (await attempt(body)).status_code == 503
            assert (await attempt({**body, **changed})).status_code == 200
            assert shim.turn_error(token) is failure
            assert (await attempt(body)).status_code == 200
            assert shim.turn_error(token) is None
    finally:
        shim.unregister_turn(token)
