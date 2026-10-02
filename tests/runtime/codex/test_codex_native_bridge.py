"""Regression for Codex-owned tools and protocol transparency (no model)."""

import asyncio
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from veadk.runtime.codex.native_bridge import NativeBridge


@pytest.mark.asyncio
async def test_mcp_schema_execution_and_lifecycle():
    calls = []

    async def execute(args, call_id):
        calls.append((args, call_id))
        return json.dumps({"value": args["value"], "status": "completed"})

    bridge = NativeBridge("http://127.0.0.1:1/v1", "synthetic")
    await bridge.start()
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }
    token = bridge.register_turn(
        [{"type": "function", "name": "echo", "parameters": schema}],
        {"echo": execute},
        max_tool_iterations=1,
    )
    try:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}
        ) as http:
            async with streamable_http_client(
                bridge.url + "/mcp", http_client=http
            ) as (read, write, _):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    listed = await client.list_tools()
                    assert listed.tools[0].inputSchema == schema
                    result = await client.call_tool("echo", {"value": 42})
                    assert json.loads(result.content[0].text)["value"] == 42
                    assert len(calls) == 1
                    invalid = await client.call_tool("echo", {"value": "wrong"})
                    assert invalid.isError
                    exhausted = await client.call_tool("echo", {"value": 7})
                    assert exhausted.isError
                    assert len(calls) == 1
        async with httpx.AsyncClient() as http:
            assert (await http.post(bridge.url + "/mcp", json={})).status_code == 401
    finally:
        await bridge.stop()
    assert bridge.active_calls == 0


@pytest.mark.asyncio
async def test_responses_are_forwarded_without_tool_loop_or_replay():
    requests = []
    body = {
        "model": "test-model",
        "stream": True,
        "input": [{"role": "user", "content": "literal <user>原题</user>"}],
        "tools": [
            {"type": "namespace", "name": "adk", "tools": []},
            {"type": "custom", "name": "apply_patch", "format": {"type": "text"}},
        ],
    }
    wire = b'event: response.failed\ndata: {"type":"response.failed","response":{"status":"failed"}}\n\n'

    async def backend(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            stream=httpx.ByteStream(wire),
            headers={"content-type": "text/event-stream"},
        )

    bridge = NativeBridge(
        "http://127.0.0.1:1/v1", "synthetic", transport=httpx.MockTransport(backend)
    )
    await bridge.start()
    token = bridge.register_turn([], {})
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                bridge.url + "/v1/responses",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.content == wire
        assert requests == [body]
        assert bridge.turn_marker(token) == ""
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_stop_cancels_and_joins_tools():
    started, finished = asyncio.Event(), asyncio.Event()

    async def execute(args, call_id):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    bridge = NativeBridge("http://127.0.0.1:1/v1", "synthetic")
    bridge.register_turn(
        [{"name": "wait", "parameters": {"type": "object"}}], {"wait": execute}
    )
    task = asyncio.create_task(bridge.execute("wait", {}))
    await started.wait()
    await bridge.stop()
    assert task.cancelled()
    assert finished.is_set()
    assert bridge.active_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["authentication_required", "confirmation_required", "pending", "transferred"],
)
async def test_pending_control_stops_tools_and_model(status):
    backend_calls, tool_calls = [], []

    async def execute(args, call_id):
        tool_calls.append(call_id)
        return json.dumps({"status": status})

    async def backend(request):
        backend_calls.append(request)
        raise AssertionError("Pending control must not reach the model")

    bridge = NativeBridge(
        "http://127.0.0.1:1/v1", "synthetic", transport=httpx.MockTransport(backend)
    )
    token = bridge.register_turn([{"name": "control"}], {"control": execute})
    try:
        await bridge.execute("control", {}, call_id="original-id")
        assert (await bridge.execute("control", {})).isError
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=bridge.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer " + token},
                json={"model": "synthetic", "input": [], "stream": False},
            )
        assert response.json()["output"] == []
        assert tool_calls == ["original-id"] and backend_calls == []
    finally:
        await bridge.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_format", ["native", "functions"])
async def test_compressed_response_is_decoded_exactly_once(tool_format):
    import gzip

    wire = b'event: response.completed\ndata: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n'

    async def backend(request):
        return httpx.Response(
            200,
            stream=httpx.ByteStream(gzip.compress(wire)),
            headers={"content-type": "text/event-stream", "content-encoding": "gzip"},
        )

    bridge = NativeBridge(
        "http://127.0.0.1:1/v1",
        "synthetic",
        transport=httpx.MockTransport(backend),
        tool_format=tool_format,
    )
    token = bridge.register_turn([], {})
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=bridge.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer " + token},
                json={"model": "synthetic", "stream": True},
            )
        frames = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert frames == [
            {
                "type": "response.completed",
                "response": {"status": "completed", "output": []},
            }
        ]
        assert (response.headers.get("content-encoding") == "gzip") == (
            tool_format == "native"
        )
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_direct_transport_retries_only_explicit_optional_summary_refusal():
    calls = []

    async def backend(request):
        body = json.loads(request.content)
        calls.append(body)
        if "summary" in body.get("reasoning", {}):
            return httpx.Response(
                400, json={"error": {"message": 'json: unknown field "summary"'}}
            )
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b'{"status":"completed","output":[]}'),
            headers={"content-type": "application/json"},
        )

    bridge = NativeBridge(
        "http://127.0.0.1:1/v1", "synthetic", transport=httpx.MockTransport(backend)
    )
    token = bridge.register_turn([], {})
    body = {
        "model": "synthetic",
        "reasoning": {"effort": "high", "summary": "auto"},
        "input": [{"type": "reasoning", "id": "keep-original"}],
    }
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=bridge.app), base_url="http://test"
        ) as client:
            for _ in range(2):
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer " + token},
                    json=body,
                )
                assert response.status_code == 200
        assert len(calls) == 3
        assert calls[0] == body
        assert calls[1] == calls[2] == {**body, "reasoning": {"effort": "high"}}
    finally:
        await bridge.stop()
