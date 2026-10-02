"""Real loopback delivery ordering; synthetic backend, no credentials/model."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from veadk.runtime.codex import proxy


def response(text="first second", *, output=None, name="reply"):
    return {
        "id": name,
        "model": "synthetic",
        "status": "completed",
        "output": output
        if output is not None
        else [
            {
                "id": "msg-" + name,
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    }


def frame(data):
    return json.loads(data.decode().split("data: ", 1)[1])


async def events(result, *, release=None, closed=None):
    try:
        async for raw in proxy._synth_sse(result):
            event = frame(raw)
            if release is not None and event["type"] == "response.output_text.delta":
                yield {**event, "delta": "first"}
                await release.wait()
                yield {**event, "delta": " second"}
            else:
                yield event
    finally:
        if closed is not None:
            closed.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("native_http", [False, True], ids=["fake", "native-http"])
async def test_socket_first_delta_precedes_backend_completion(monkeypatch, native_http):
    release = asyncio.Event()
    closed = asyncio.Event()
    requested = []

    async def backend(**kwargs):
        requested.append(kwargs["stream"])
        if kwargs["stream"]:
            return events(response(), release=release, closed=closed)
        await release.wait()
        return response()

    upstream = None
    api_base = "https://synthetic.invalid/v1"
    if native_http:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()

        # No postponed annotation of a local-only Request type: FastAPI needs
        # the actual class object to inject the HTTP request.
        async def endpoint(request):
            result = await backend(**await request.json())
            if not hasattr(result, "__aiter__"):
                return JSONResponse(result)

            async def body():
                async for event in result:
                    yield proxy._sse(event)

            return StreamingResponse(body(), media_type="text/event-stream")

        endpoint.__annotations__["request"] = Request
        app.post("/v1/responses")(endpoint)
        upstream = proxy.ResponsesShim("unused", "synthetic")
        upstream._app = app
        await upstream.start()
        api_base = upstream.url + "/v1"
    else:
        monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim(api_base, "synthetic")
    token = shim.register_turn([], {})
    await shim.start()
    received = []

    async def consume():
        async with httpx.AsyncClient(timeout=5) as client:
            async with client.stream(
                "POST",
                shim.url + "/v1/responses",
                headers={"Authorization": "Bearer " + token},
                json={"model": "synthetic", "stream": True, "input": "go"},
            ) as result:
                async for line in result.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    received.append(event)
                    if (
                        event["type"] == "response.output_text.delta"
                        and not release.is_set()
                    ):
                        assert not closed.is_set()
                        release.set()

    try:
        await asyncio.wait_for(consume(), 2)
    finally:
        release.set()
        await shim.stop()
        if upstream is not None:
            await upstream.stop()

    assert requested == [True]
    assert closed.is_set()
    assert [
        e["delta"] for e in received if e["type"] == "response.output_text.delta"
    ] == ["first", " second"]
    assert received[-1]["type"] == "response.completed"
    assert [e["sequence_number"] for e in received] == list(range(len(received)))
    assert received[-1]["response"]["output"] == [
        e["item"] for e in received if e["type"] == "response.output_item.done"
    ]


async def post(shim, token):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=shim._app), base_url="http://shim"
    ) as client:
        result = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer " + token},
            json={
                "model": "synthetic",
                "stream": True,
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "go"}],
                    }
                ],
            },
        )
    return [
        json.loads(line[6:])
        for line in result.text.splitlines()
        if line.startswith("data: ")
    ]


def call(name, cid="call-1"):
    return {
        "id": "fc-" + cid,
        "type": "function_call",
        "call_id": cid,
        "name": name,
        "arguments": '{"dc":"yumc1"}',
        "status": "completed",
    }


@pytest.mark.asyncio
async def test_stream_tool_round_hides_adk_retains_native_and_sums_usage(monkeypatch):
    executed = []
    requests = []

    async def tool(args, call_id):
        executed.append((args, call_id))
        return '{"rows":149254}'

    shim = proxy.ResponsesShim("https://synthetic.invalid/v1", "synthetic")
    token = shim.register_turn(
        [{"type": "function", "name": "query", "parameters": {}}], {"query": tool}
    )

    async def backend(**kwargs):
        requests.append(json.loads(json.dumps(kwargs["input"])))
        if len(requests) == 1:
            preamble = response("Investigating", name="preamble")["output"][0]
            return events(response(output=[preamble, call("query")], name="tools"))
        assert requests[-1][-2]["type"] == "function_call"
        assert requests[-1][-1]["output"] == '{"rows":149254}'
        return events(response(output=[call("native", "native-1")], name="native"))

    monkeypatch.setattr(proxy, "_request_backend", backend)
    frames = await post(shim, token)
    assert executed == [({"dc": "yumc1"}, "call-1")]
    assert len(requests) == 2
    assert frames[-1]["type"] == "response.completed"
    completed = frames[-1]["response"]
    assert completed["usage"]["total_tokens"] == 24
    assert completed["output"][0]["phase"] == "commentary"
    assert [i["name"] for i in completed["output"] if i["type"] == "function_call"] == [
        "native"
    ]
    assert completed["output"] == [
        e["item"] for e in frames if e["type"] == "response.output_item.done"
    ]
    assert [e["sequence_number"] for e in frames] == list(range(len(frames)))
    assert len([e for e in frames if e["type"] == "response.created"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending", ["eof", "failed", "incomplete", "exception", "changed_text"]
)
async def test_partial_or_changed_report_is_never_completed(monkeypatch, ending):
    closed = asyncio.Event()

    async def broken():
        try:
            async for event in events(response()):
                if event["type"] == "response.completed":
                    if ending == "exception":
                        raise ValueError("private-provider-error-must-not-escape")
                    if ending in ("failed", "incomplete"):
                        yield {
                            "type": "response." + ending,
                            "response": {
                                "error": "private-provider-error-must-not-escape"
                            },
                        }
                    elif ending == "changed_text":
                        final = response("different report")
                        yield {**event, "response": final}
                    return
                yield event
        finally:
            closed.set()

    async def backend(**kwargs):
        return broken()

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("https://synthetic.invalid/v1", "synthetic")
    token = shim.register_turn([], {})
    frames = await post(shim, token)
    assert any(e["type"] == "response.output_text.delta" for e in frames)
    assert frames[-1]["type"] == "response.failed"
    assert not any(e["type"] == "response.completed" for e in frames)
    assert frames[-1]["response"]["error"]["code"] == proxy._FATAL_STREAM_ERROR_CODE
    assert "private-provider" not in json.dumps(frames)
    assert shim._turn(token).state.error is not None
    assert closed.is_set()


@pytest.mark.asyncio
async def test_completed_only_bridge_gets_canonical_stream(monkeypatch):
    async def completed_only():
        yield {"type": "response.completed", "response": response()}

    async def backend(**kwargs):
        return completed_only()

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("https://synthetic.invalid/v1", "synthetic")
    token = shim.register_turn([], {})
    frames = await post(shim, token)
    assert frames[0]["type"] == "response.created"
    assert frames[-1]["type"] == "response.completed"
    assert [
        e["delta"] for e in frames if e["type"] == "response.output_text.delta"
    ] == ["first second"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "incomplete"])
@pytest.mark.parametrize("native", [False, True])
async def test_unsuccessful_terminal_retains_body_and_does_not_execute_tools(
    monkeypatch, status, native
):
    executed = []
    requests = []
    final = response("Synthetic partial report")
    final["status"] = status
    final["output"].append(call("query"))
    if status == "failed":
        final["error"] = {"code": "server_error", "message": "Synthetic failure"}
    else:
        final["incomplete_details"] = {"reason": "max_output_tokens"}

    async def terminal_stream():
        async for event in events(final):
            if event["type"] == "response.completed":
                event = {**event, "type": f"response.{status}", "response": final}
            yield event

    async def backend(**kwargs):
        requests.append(True)
        assert len(requests) == 1, "failed_response_started_another_model_round"
        return terminal_stream() if native else final

    async def query(args, call_id):
        executed.append(call_id)
        return "Synthetic evidence"

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("https://synthetic.invalid/v1", "synthetic")
    token = shim.register_turn(
        [{"type": "function", "name": "query", "parameters": {}}], {"query": query}
    )
    try:
        frames = await post(shim, token)
        assert not executed, "tool_executed_from_unsuccessful_response"
        assert frames[-1]["type"] == f"response.{status}"
        assert frames[-1]["response"]["status"] == status
        assert not any(e["type"] == "response.completed" for e in frames)
        output = frames[-1]["response"]["output"]
        assert output == [
            e["item"] for e in frames if e["type"] == "response.output_item.done"
        ]
        assert [i["content"][0]["text"] for i in output if i["type"] == "message"] == [
            "Synthetic partial report"
        ]
        assert not any(i["type"] == "function_call" for i in output)
        assert shim.turn_error(token) is not None
    finally:
        shim.unregister_turn(token)


@pytest.mark.asyncio
async def test_socket_disconnect_closes_upstream(monkeypatch):
    closed = asyncio.Event()
    release = asyncio.Event()

    async def backend(**kwargs):
        return events(response(), release=release, closed=closed)

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("https://synthetic.invalid/v1", "synthetic")
    token = shim.register_turn([], {})
    await shim.start()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            async with client.stream(
                "POST",
                shim.url + "/v1/responses",
                headers={"Authorization": "Bearer " + token},
                json={"model": "synthetic", "stream": True, "input": "go"},
            ) as result:
                async for line in result.aiter_lines():
                    if line.startswith("event: response.output_text.delta"):
                        break
        await asyncio.wait_for(closed.wait(), 2)
        assert not release.is_set()
    finally:
        release.set()
        await shim.stop()


def test_completed_commentary_cannot_enter_final_report():
    from veadk.runtime.codex.translate import item_to_events, is_codex_final_text_event

    events = item_to_events(
        {
            "type": "agentMessage",
            "id": "preamble",
            "phase": "commentary",
            "text": "Investigating",
        },
        "expert",
        "invocation",
    )
    assert events and all(e.partial for e in events)
    assert not any(is_codex_final_text_event(e) for e in events)


@pytest.mark.asyncio
async def test_cancelled_producer_does_not_leave_consumer_waiting():
    from veadk.runtime.codex.streaming import ResponsesStream

    relay = ResponsesStream(
        model="synthetic",
        executors={},
        synthesize=proxy._synth_sse,
        record_error=lambda e: None,
        fatal_code=proxy._FATAL_STREAM_ERROR_CODE,
    )

    async def operation():
        raise asyncio.CancelledError()

    async def consume():
        return [part async for part in relay.run(operation)]

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consume(), 1)


@pytest.mark.asyncio
async def test_native_transport_preserves_thinking_tools_and_closes_owned_client(
    monkeypatch,
):
    from veadk.runtime.codex import native_responses

    seen = {}

    class Stream:
        async def close(self):
            seen["stream_closed"] = True

        def __aiter__(self):
            return events(response())

    class Client:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.responses = self

        async def create(self, **kwargs):
            seen["request"] = kwargs
            return Stream()

        async def close(self):
            seen["client_closed"] = True

    monkeypatch.setattr(native_responses, "AsyncOpenAI", Client)
    request = {
        "model": "openai/unknown-provider-model",
        "input": [],
        "stream": True,
        "api_base": "https://synthetic.invalid/v1",
        "api_key": "synthetic",
        "num_retries": 2,
        "timeout": 7,
        "custom_llm_provider": "openai",
        "drop_params": True,
        "extra_body": {"thinking": {"type": "enabled"}},
        "extra_headers": {"x-trace": "synthetic"},
        "tools": [{"type": "function", "name": "query", "parameters": {}}],
    }
    before = json.loads(json.dumps(request))
    stream = await proxy._request_backend(**request)
    await stream.aclose()
    assert request == before
    assert seen["request"]["model"] == "unknown-provider-model"
    assert seen["request"]["stream"] is True
    for key in ("extra_body", "extra_headers", "tools", "input"):
        assert seen["request"][key] == request[key]
    assert seen["client"]["max_retries"] == 2
    assert seen["client"]["timeout"] == 7
    assert seen["stream_closed"] and seen["client_closed"]


@pytest.mark.asyncio
async def test_native_bad_request_repairs_only_summary_and_closes_failed_client(
    monkeypatch,
):
    from openai import BadRequestError
    from veadk.runtime.codex import native_responses

    clients = []
    requests = []

    class Client:
        def __init__(self, **kwargs):
            clients.append(self)
            self.responses = self
            self.closed = False

        async def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                raise BadRequestError(
                    'json: unknown field "summary"',
                    response=httpx.Response(
                        400,
                        request=httpx.Request(
                            "POST", "https://synthetic.invalid/v1/responses"
                        ),
                    ),
                    body={},
                )

            class Stream:
                async def close(self):
                    pass

            return Stream()

        async def close(self):
            self.closed = True

    monkeypatch.setattr(native_responses, "AsyncOpenAI", Client)
    state = proxy.TurnToolState()
    kwargs = {
        "model": "openai/synthetic",
        "input": [],
        "stream": True,
        "api_base": "https://synthetic.invalid/v1",
        "api_key": "synthetic",
        "reasoning": {"effort": "high", "summary": "auto"},
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    stream = await proxy._call_backend_tolerating_reasoning(kwargs, state=state)
    assert clients[0].closed
    assert requests[1]["reasoning"] == {"effort": "high"}
    assert requests[1]["extra_body"] == kwargs["extra_body"]
    assert kwargs["reasoning"]["summary"] == "auto"
    assert state.summary_option_rejected("openai/synthetic")
    await stream.aclose()
    assert clients[1].closed


@pytest.mark.asyncio
async def test_distinct_http_responses_never_reuse_stream_item_ids(monkeypatch):
    async def backend(**kwargs):
        return events(response())

    monkeypatch.setattr(proxy, "_request_backend", backend)
    shim = proxy.ResponsesShim("https://synthetic.invalid/v1", "synthetic")
    token = shim.register_turn([], {})
    first = await post(shim, token)
    second = await post(shim, token)

    def ids(frames):
        return {i["id"] for i in frames[-1]["response"]["output"]}

    assert ids(first).isdisjoint(ids(second))
