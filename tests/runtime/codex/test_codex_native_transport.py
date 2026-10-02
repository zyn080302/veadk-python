"""Provider projection preserves all native item types and terminal statuses."""

import json

import pytest

from veadk.runtime.codex.native_transport import encode_backend_result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "incomplete", "failed"])
async def test_buffered_projection_keeps_terminal_and_all_tool_items(status):
    output = [
        {
            "type": "custom_tool_call",
            "name": "apply_patch",
            "call_id": "patch",
            "input": "exact\npatch",
        },
        {
            "type": "tool_search_call",
            "execution": "client",
            "call_id": "search",
            "arguments": {"query": "docs"},
        },
    ]
    original = {"status": status, "output": output, "usage": {"total_tokens": 19}}
    wire = b"".join([chunk async for chunk in encode_backend_result(original)])
    events = [
        json.loads(line[6:])
        for line in wire.decode().splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1] == {"type": "response." + status, "response": original}
    assert [
        e["item"] for e in events if e["type"] == "response.output_item.done"
    ] == output


@pytest.mark.asyncio
async def test_stream_projection_closes_owned_stream_on_abandonment():
    class Stream:
        closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            return {"type": "response.output_text.delta", "delta": "original"}

        async def aclose(self):
            self.closed = True

    backend = Stream()
    stream = encode_backend_result(backend)
    assert b"original" in await anext(stream)
    await stream.aclose()
    assert backend.closed


@pytest.mark.asyncio
async def test_explicit_summary_refusal_only_removes_that_preference():
    from copy import deepcopy
    from veadk.runtime.codex.native_transport import SummaryCompatibility

    class Rejection(Exception):
        status_code = 400

    calls = []

    async def backend(**kwargs):
        calls.append(deepcopy(kwargs))
        if "summary" in kwargs.get("reasoning", {}):
            raise Rejection('json: unknown field "summary"')
        return "ok"

    original = {
        "model": "synthetic",
        "reasoning": {"effort": "high", "summary": "auto"},
        "input": [{"type": "reasoning", "id": "keep-original"}],
    }
    adapter = SummaryCompatibility()
    assert await adapter.call(backend, **original) == "ok"
    assert await adapter.call(backend, **original) == "ok"
    assert len(calls) == 3
    assert calls[0] == original
    assert calls[1] == calls[2] == {**original, "reasoning": {"effort": "high"}}
    assert "summary" in original["reasoning"]

    async def other(**kwargs):
        raise Rejection("unrelated refusal")

    with pytest.raises(Rejection, match="unrelated"):
        await adapter.call(other, **original)
