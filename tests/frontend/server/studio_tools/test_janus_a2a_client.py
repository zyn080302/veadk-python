# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from frontend.server.studio_tools.janus_a2a_client import (
    JanusA2AClient,
    JanusA2AError,
    JanusContextStore,
)


def _cancellable_agent_card() -> dict[str, Any]:
    return {
        "name": "Janus",
        "capabilities": {
            "extensions": [
                {
                    "uri": "urn:volcengine:janus:task-cancellation",
                    "version": "janus-task-cancel-v1",
                }
            ]
        },
    }


def _approval_agent_card() -> dict[str, Any]:
    card = _cancellable_agent_card()
    card["capabilities"]["extensions"].insert(
        0,
        {
            "uri": "urn:volcengine:janus:browser-action-approval",
            "version": "browser-action-approval-v1",
        },
    )
    return card


@pytest.mark.asyncio
async def test_client_discovers_agent_card_and_uses_standard_message_send() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    **_cancellable_agent_card(),
                    "url": "http://janus.test/a2a",
                },
            )
        body = json.loads(request.content)
        assert body["method"] == "message/send"
        message = body["params"]["message"]
        assert message["parts"] == [{"kind": "text", "text": "Open example.com"}]
        assert message["metadata"] == {"browserLocation": "cloud"}
        assert "ownerId" not in message["metadata"]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "kind": "message",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "done"}],
                    "contextId": "context-1",
                },
            },
        )

    client = JanusA2AClient(
        "http://janus.test",
        transport=httpx.MockTransport(handler),
    )

    result = await client.send_browser_task(
        task="Open example.com",
        browser_location="cloud",
        context_key=("owner-1", "runtime-1", "app", "user", "session"),
    )

    assert result == {
        "status": "completed",
        "text": "done",
        "contextId": "context-1",
        "metadata": {},
    }
    assert [request.url.path for request in requests] == [
        "/.well-known/agent-card.json",
        "/a2a",
    ]


@pytest.mark.asyncio
async def test_client_preserves_private_sandbox_endpoint_auth_query() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_cancellable_agent_card())
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "kind": "message",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "done"}],
                    "contextId": "context-1",
                },
            },
        )

    client = JanusA2AClient(
        "https://sandbox.example/private?Authorization=secret&instance=one",
        transport=httpx.MockTransport(handler),
    )

    await client.send_browser_task(
        task="Open example.com",
        browser_location="cloud",
        context_key=("owner-1", "runtime-1", "app", "user", "session"),
    )

    assert [request.url.path for request in requests] == [
        "/private/.well-known/agent-card.json",
        "/private/a2a",
    ]
    assert [dict(request.url.params) for request in requests] == [
        {"Authorization": "secret", "instance": "one"},
        {"Authorization": "secret", "instance": "one"},
    ]


@pytest.mark.asyncio
async def test_context_store_reuses_same_location_and_rejects_switch() -> None:
    messages: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_cancellable_agent_card())
        body = json.loads(request.content)
        message = body["params"]["message"]
        messages.append(message)
        context_id = message.get("contextId") or f"context-{len(messages)}"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "kind": "message",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "ok"}],
                    "contextId": context_id,
                },
            },
        )

    client = JanusA2AClient(
        "http://janus.test",
        transport=httpx.MockTransport(handler),
        context_store=JanusContextStore(),
    )
    key = ("owner-1", "runtime-1", "app", "user", "session")

    await client.send_browser_task(
        task="first", browser_location="cloud", context_key=key
    )
    await client.send_browser_task(
        task="second", browser_location="cloud", context_key=key
    )
    with pytest.raises(JanusA2AError, match="locked to cloud"):
        await client.send_browser_task(
            task="local", browser_location="local", context_key=key
        )

    assert "contextId" not in messages[0]
    assert messages[1]["contextId"] == "context-1"
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_concurrent_first_turns_cannot_create_cross_location_contexts() -> None:
    first_request_entered = asyncio.Event()
    release_first_request = asyncio.Event()
    locations: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_cancellable_agent_card())
        body = json.loads(request.content)
        message = body["params"]["message"]
        location = message["metadata"]["browserLocation"]
        locations.append(location)
        if len(locations) == 1:
            first_request_entered.set()
            await release_first_request.wait()
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "kind": "message",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "ok"}],
                    "contextId": f"context-{location}",
                },
            },
        )

    client = JanusA2AClient(
        "http://janus.test",
        transport=httpx.MockTransport(handler),
        context_store=JanusContextStore(),
    )
    key = ("owner-1", "runtime-1", "app", "user", "session")
    cloud = asyncio.create_task(
        client.send_browser_task(
            task="cloud first",
            browser_location="cloud",
            context_key=key,
        )
    )
    await first_request_entered.wait()
    local = asyncio.create_task(
        client.send_browser_task(
            task="local concurrently",
            browser_location="local",
            context_key=key,
        )
    )
    for _ in range(3):
        await asyncio.sleep(0)
    release_first_request.set()

    cloud_result, local_result = await asyncio.gather(
        cloud,
        local,
        return_exceptions=True,
    )

    assert cloud_result["contextId"] == "context-cloud"
    assert isinstance(local_result, JanusA2AError)
    assert "locked to cloud" in str(local_result)
    assert locations == ["cloud"]


@pytest.mark.asyncio
async def test_client_injects_approval_id_as_trusted_a2a_metadata() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_approval_agent_card())
        body = json.loads(request.content)
        message = body["params"]["message"]
        seen.append(message)
        if len(seen) == 1:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "kind": "message",
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "approval required"}],
                        "contextId": "context-approved",
                        "metadata": {
                            "status": "approval_required",
                            "approvalId": "approval-opaque",
                            "actionDigest": "a" * 64,
                            "actionSummary": "发布公告",
                            "targetOrigin": "https://console.example.com",
                            "riskLevel": "high",
                            "expiresAt": "2099-09-15T12:00:00Z",
                            "capabilityVersion": "browser-action-approval-v1",
                        },
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "kind": "message",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "approved"}],
                },
            },
        )

    client = JanusA2AClient(
        "http://janus.test",
        transport=httpx.MockTransport(handler),
    )
    key = ("owner-1", "runtime-1", "app", "user", "session")
    prepared = await client.send_browser_task(
        task="prepare publish",
        browser_location="local",
        risk_level="high",
        context_key=key,
    )
    await client.send_browser_task(
        task="publish",
        browser_location="local",
        risk_level="high",
        approval_id="approval-opaque",
        context_key=key,
    )

    assert prepared["approval"]["approvalId"] == "approval-opaque"
    assert seen[0]["metadata"] == {"browserLocation": "local"}
    assert seen[1]["metadata"] == {
        "browserLocation": "local",
        "approvalId": "approval-opaque",
    }
    assert seen[1]["contextId"] == "context-approved"


@pytest.mark.asyncio
async def test_client_rejects_write_when_janus_lacks_approval_capability() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_cancellable_agent_card())

    client = JanusA2AClient(
        "http://janus.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(JanusA2AError, match="approval capability"):
        await client.send_browser_task(
            task="publish",
            browser_location="cloud",
            risk_level="high",
            context_key=("owner-1", "runtime-1", "app", "user", "session"),
        )

    assert [request.method for request in requests] == ["GET"]


@pytest.mark.asyncio
async def test_cancelled_studio_tool_propagates_standard_a2a_task_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancel_requests: list[dict[str, Any]] = []
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "frontend.server.studio_tools.janus_a2a_client.emit_browser_event",
        lambda event, **fields: events.append((event, fields)),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_cancellable_agent_card())
        body = json.loads(request.content)
        if body["method"] == "message/send":
            assert body["params"]["message"]["contextId"] == "context-existing"
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("message/send must remain pending until canceled")
        cancel_requests.append(body)
        assert body["method"] == "tasks/cancel"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "id": body["params"]["id"],
                    "contextId": "context-1",
                    "status": {"state": "canceled"},
                },
            },
        )

    context_store = JanusContextStore()
    context_key = ("owner-1", "runtime-1", "app", "user", "session")
    await context_store.put(context_key, "cloud", "context-existing")
    client = JanusA2AClient(
        "http://janus.test",
        transport=httpx.MockTransport(handler),
        context_store=context_store,
    )
    send = asyncio.create_task(
        client.send_browser_task(
            task="keep browsing",
            browser_location="cloud",
            context_key=context_key,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    send.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(send, timeout=1)

    assert len(cancel_requests) == 1
    assert cancel_requests[0]["params"]["id"]
    assert cancel_requests[0]["params"]["id"] != cancel_requests[0]["id"]
    assert await context_store.get(context_key, "cloud") is None
    assert [event for event, _fields in events] == [
        "browser_context_reused",
        "browser_context_closed",
    ]
    assert "keep browsing" not in repr(events)
