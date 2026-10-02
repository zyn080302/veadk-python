"""The real Python SDK must preserve fields emitted by newer Codex CLIs."""

import json

import httpx
import pytest
from openai import AsyncOpenAI

from veadk.runtime.codex import native_responses


def install_client(monkeypatch, observed):
    async def send(request):
        observed.append(json.loads(request.content))
        response = {
            "id": "synthetic-response",
            "object": "response",
            "created_at": 0,
            "model": "synthetic",
            "status": "completed",
            "output": [],
        }
        event = {"type": "response.completed", "response": response}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=("data: " + json.dumps(event) + "\n\n").encode(),
        )

    def client(**kwargs):
        return AsyncOpenAI(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(send)),
            **kwargs,
        )

    monkeypatch.setattr(native_responses, "AsyncOpenAI", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["client_metadata", "future_protocol_option"])
async def test_new_wire_fields_reach_http_unchanged(monkeypatch, field):
    observed = []
    install_client(monkeypatch, observed)
    value = {"synthetic": ["one", 2, True]}
    stream = await native_responses.request_native_stream(
        api_base="http://127.0.0.1:1/v1",
        api_key="synthetic",
        model="openai/synthetic",
        stream=True,
        input=[{"role": "user", "content": "original question"}],
        extra_body={"thinking": {"type": "enabled"}},
        **{field: value},
    )
    try:
        events = [event async for event in stream]
    finally:
        await stream.aclose()
    assert [e.type for e in events] == ["response.completed"]
    assert len(observed) == 1
    assert observed[0][field] == value
    assert observed[0]["thinking"] == {"type": "enabled"}
    assert observed[0]["input"] == [{"role": "user", "content": "original question"}]
    assert observed[0]["model"] == "synthetic"


@pytest.mark.asyncio
async def test_extension_collision_is_explicit_before_sending(monkeypatch):
    observed = []
    install_client(monkeypatch, observed)
    with pytest.raises(ValueError, match="Conflicting Responses field"):
        await native_responses.request_native_stream(
            api_base="http://127.0.0.1:1/v1",
            api_key="synthetic",
            model="synthetic",
            stream=True,
            input="question",
            client_metadata={"value": "native"},
            extra_body={"client_metadata": {"value": "override"}},
        )
    assert observed == []
