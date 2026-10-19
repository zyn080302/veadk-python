"""Offline contracts for the managed Shared channel, not ordinary Studio."""

import asyncio
import hashlib
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from veadk.runtime.customer import (
    CustomerChannelClient,
    CustomerChannelError,
    CustomerRunRequest,
    CustomerSkill,
    CustomerTool,
)


def request(**changes):
    return CustomerRunRequest(
        app_name="managed_example",
        user_id=changes.pop("user_id", "user-a"),
        session_id="session-a",
        new_message={"role": "user", "parts": [{"text": "查询企业"}]},
        agent_config=SecretStr("synthetic-config-only"),
        environment={"MODEL_EXAMPLE": SecretStr("synthetic-value-only")},
        **changes,
    )


def tool(**changes):
    return CustomerTool(
        name=changes.pop("name", "lookup"),
        description="查询企业",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        executor_revision="executor-v1",
        source=changes.pop("source", "mcp"),
        **changes,
    )


def ready():
    return {
        "type": "channel.ready",
        "protocol": "studio-tool-channel/1",
        "transport": "http-sse",
    }


def complete(run, status="success"):
    return {"type": "run.completed", "run_id": run.run_id, "status": status}


def call(run, **changes):
    return {
        "type": "tool.call",
        "request_id": "call-a",
        "run_id": run.run_id,
        "scope_id": run.scope_id,
        "catalog_revision": run.catalog_revision,
        "tool_name": "lookup",
        "executor_revision": "executor-v1",
        "arguments": {"name": "企业"},
        "deadline_ms": 600000,
        **changes,
    }


class Stream(httpx.AsyncByteStream):
    def __init__(self, messages=(), raw=None, wait=False):
        self.body = (
            raw
            if raw is not None
            else b"".join(
                ("data: " + json.dumps(m, ensure_ascii=False) + "\r\n\r\n").encode()
                for m in messages
            )
        )
        self.closed = False
        self.wait = wait

    async def __aiter__(self):
        # Split UTF-8 and CRLF at every possible byte boundary.
        for byte in self.body:
            yield bytes([byte])
        if self.wait:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


class Host:
    def __init__(self, stream):
        self.stream = stream
        self.requests = []
        self.result_status = 200

    async def handle(self, req):
        self.requests.append(req)
        if req.url.path.endswith("/http-runs"):
            return httpx.Response(
                200,
                stream=self.stream,
                headers={
                    "content-type": "text/event-stream",
                    "X-Session-Id": "affinity-b",
                },
            )
        if req.url.path.endswith("/capabilities"):
            return httpx.Response(
                200,
                json={
                    "enabled": True,
                    "protocol": "studio-tool-channel/1",
                    "transports": ["http-sse"],
                    "skills": True,
                },
                headers={"X-Session-Id": "affinity-a"},
            )
        if req.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"id": "session-a"})
        return httpx.Response(
            self.result_status,
            json={"accepted": True},
            headers={"X-Session-Id": "affinity-c"},
        )

    def client(self, **kwargs):
        return CustomerChannelClient(
            "https://runtime.invalid",
            transport=httpx.MockTransport(self.handle),
            headers=lambda: {"Authorization": "Bearer synthetic-header-only"},
            **kwargs,
        )


@pytest.mark.asyncio
async def test_exact_shared_wire_and_affinity():
    run = request(
        tools=(tool(),),
        skills=(
            CustomerSkill(
                name="company-research",
                description="research",
                instructions="use evidence",
                references={"guide.md": "all pages"},
                assets={"format.txt": "company"},
            ),
        ),
    )
    host = Host(Stream([ready(), call(run), complete(run)]))
    async with host.client() as client:
        capabilities = await client.capabilities()
        assert capabilities["protocol"] == "studio-tool-channel/1"
        await client.create_session("managed_example", "user-a", "session-a")
        async with client.run(run) as channel:
            async for event in channel.events():
                if event["type"] == "tool.call":
                    await channel.submit_result("call-a", content={"pages": [1, 2]})
    cap, session, start, result = host.requests
    assert cap.headers.get("X-Session-Id") is None
    assert session.headers["X-Session-Id"] == "affinity-a"
    assert json.loads(session.content) == {"sessionId": "session-a"}
    assert start.headers["X-Session-Id"] == "affinity-a"
    assert result.headers["X-Session-Id"] == "affinity-b"
    wire = json.loads(start.content)
    assert wire["agent_config"] == "synthetic-config-only"
    assert wire["environment"] == {"MODEL_EXAMPLE": "synthetic-value-only"}
    assert wire["payload"]["session_id"] == "session-a"
    assert "sessionId" not in wire["payload"]
    assert wire["tools"][0]["timeout_ms"] == 600000
    assert wire["tools"][0]["source"] == "mcp"
    canonical = json.dumps(
        wire["tools"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert wire["catalog_revision"] == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert wire["skills"][0]["scripts"] == {}
    assert wire["skills"][0]["references"] == {"guide.md": "all pages"}
    assert json.loads(result.content) == {
        "type": "tool.result",
        "request_id": "call-a",
        "run_id": run.run_id,
        "scope_id": run.scope_id,
        "catalog_revision": run.catalog_revision,
        "status": "success",
        "content": {"pages": [1, 2]},
        "error": "",
    }
    assert host.stream.closed
    assert "synthetic" not in repr(run)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending,code",
    [
        (None, "incomplete_stream"),
        ("error", "run_error"),
        ("cancelled", "run_cancelled"),
    ],
)
async def test_only_success_terminal_is_success(ending, code):
    run = request()
    host = Host(Stream([ready()] + ([complete(run, ending)] if ending else [])))
    async with host.client() as client:
        with pytest.raises(CustomerChannelError, match=code):
            async with client.run(run) as channel:
                async for _ in channel.events():
                    pass
    assert host.stream.closed
    cancels = [r for r in host.requests if r.url.path.endswith("/messages")]
    assert len(cancels) == (1 if ending is None else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "stale"},
        {"scope_id": "stale"},
        {"catalog_revision": "stale"},
        {"executor_revision": "stale"},
        {"tool_name": "shell"},
        {"arguments": {"name": 123}},
        {"deadline_ms": 1800001},
    ],
)
async def test_invalid_tool_never_reaches_executor(change):
    run = request(tools=(tool(),))
    host = Host(Stream([ready(), call(run, **change), complete(run)]))
    exposed = []
    async with host.client() as client:
        with pytest.raises(CustomerChannelError):
            async with client.run(run) as channel:
                async for event in channel.events():
                    exposed.append(event["type"])
    assert "tool.call" not in exposed
    assert all(
        json.loads(r.content)["type"] == "run.cancel"
        for r in host.requests
        if r.url.path.endswith("/messages")
    )


@pytest.mark.asyncio
async def test_duplicate_call_is_not_exposed_twice():
    run = request(tools=(tool(),))
    host = Host(Stream([ready(), call(run), call(run)]))
    calls = 0
    async with host.client() as client:
        with pytest.raises(CustomerChannelError, match="duplicate_tool_call"):
            async with client.run(run) as channel:
                async for event in channel.events():
                    if event["type"] == "tool.call":
                        calls += 1
                        await channel.submit_result("call-a", content={})
                        with pytest.raises(
                            CustomerChannelError, match="stale_tool_result"
                        ):
                            await channel.submit_result("call-a", content={})
    assert calls == 1


@pytest.mark.asyncio
async def test_ambiguous_result_delivery_is_not_retried():
    run = request(tools=(tool(),))
    host = Host(Stream([ready(), call(run), complete(run)]))
    host.result_status = 503
    async with host.client() as client:
        async with client.run(run) as channel:
            async for event in channel.events():
                if event["type"] == "tool.call":
                    with pytest.raises(CustomerChannelError, match="http_status_503"):
                        await channel.submit_result("call-a", content={})
                    with pytest.raises(CustomerChannelError, match="stale_tool_result"):
                        await channel.submit_result("call-a", content={})
    assert len([r for r in host.requests if r.url.path.endswith("/messages")]) == 1


@pytest.mark.asyncio
async def test_tool_cancel_invalidates_submission():
    run = request(tools=(tool(),))
    host = Host(
        Stream(
            [
                ready(),
                call(run),
                {
                    "type": "tool.cancel",
                    "run_id": run.run_id,
                    "request_id": "call-a",
                },
                complete(run),
            ]
        )
    )
    async with host.client() as client:
        async with client.run(run) as channel:
            async for event in channel.events():
                if event["type"] == "tool.cancel":
                    with pytest.raises(CustomerChannelError, match="stale_tool_result"):
                        await channel.submit_result("call-a", content={})
    assert len(host.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["early", "cancel", "timeout"])
async def test_run_cleanup_and_next_send(exit_mode):
    run = request()
    host = Host(Stream([ready()], wait=True))
    entered = asyncio.Event()
    async with host.client(
        turn_timeout=0.03 if exit_mode == "timeout" else 10
    ) as client:

        async def consume():
            async with client.run(run) as channel:
                async for _ in channel.events():
                    entered.set()
                    if exit_mode == "early":
                        break

        task = asyncio.create_task(consume())
        await entered.wait()
        if exit_mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif exit_mode == "timeout":
            with pytest.raises(CustomerChannelError, match="run_timeout"):
                await task
        else:
            await task
        assert host.stream.closed
        assert json.loads(host.requests[-1].content)["type"] == "run.cancel"
        next_run = request()
        host.stream = Stream([ready(), complete(next_run)])
        async with client.run(next_run) as channel:
            async for _ in channel.events():
                pass
    assert len(host.requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,code",
    [
        (b"data: {broken}\n\n", "invalid_event"),
        (b'data: {"type":"unknown"}\n\n', "invalid_event"),
        (b"data: " + b"x" * 2000, "event_too_large"),
        (b"data: \xff\n\n", "invalid_event"),
    ],
)
async def test_malformed_and_unbounded_sse_rejected(raw, code):
    host = Host(Stream(raw=raw))
    async with host.client(max_event_bytes=1024) as client:
        with pytest.raises(CustomerChannelError, match=code):
            async with client.run(request()) as channel:
                async for _ in channel.events():
                    pass
    assert host.stream.closed


@pytest.mark.asyncio
async def test_no_redirects_no_retry_and_error_redaction():
    requests = []

    async def handler(req):
        requests.append(req)
        return httpx.Response(
            429,
            text="synthetic-private-response",
            headers={"Location": "https://elsewhere.invalid"},
        )

    async with CustomerChannelClient(
        "https://runtime.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(CustomerChannelError) as caught:
            await client.capabilities()
    assert str(caught.value) == "http_status_429"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:pass@runtime.invalid",
        "https://runtime.invalid/?private=yes",
        "https://runtime.invalid/#fragment",
        "http://runtime.invalid",
        "file:///etc/passwd",
    ],
)
def test_unsafe_endpoint_is_rejected_without_echo(endpoint):
    with pytest.raises(ValueError) as caught:
        CustomerChannelClient(endpoint)
    assert endpoint not in str(caught.value)


def test_readonly_skills_and_separate_shared_schema():
    with pytest.raises(ValidationError):
        CustomerSkill(
            name="research",
            description="research",
            instructions="read",
            scripts={"run.py": "print(1)"},
        )
    with pytest.raises(ValidationError):
        tool(source="extension")


@pytest.mark.parametrize(
    "setting", ["operation_timeout", "turn_timeout", "cleanup_timeout"]
)
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_nonfinite_or_unbounded_deadlines_rejected(setting, value):
    with pytest.raises(ValueError):
        CustomerChannelClient("https://runtime.invalid", **{setting: value})


@pytest.mark.asyncio
async def test_snapshot_cannot_change_during_run():
    manifest = tool()
    run = request(tools=(manifest,))
    host = Host(Stream([ready(), call(run), complete(run)]))
    async with host.client() as client:
        async with client.run(run) as channel:
            # Mutating the caller's nested dictionaries cannot relax validation.
            manifest.input_schema["properties"]["name"]["type"] = "number"
            run.new_message["parts"].clear()
            async for event in channel.events():
                if event["type"] == "tool.call":
                    await channel.submit_result("call-a", content={})
    assert json.loads(host.requests[0].content)["payload"]["new_message"]["parts"]


@pytest.mark.asyncio
async def test_deadline_and_cancelled_delivery_consume_pending_call():
    run = request(tools=(tool(),))
    host = Host(Stream([ready(), call(run, deadline_ms=1), complete(run)]))
    async with host.client() as client:
        async with client.run(run) as channel:
            async for event in channel.events():
                if event["type"] == "tool.call":
                    await asyncio.sleep(0.005)
                    with pytest.raises(CustomerChannelError, match="stale_tool_result"):
                        await channel.submit_result("call-a", content={})
    assert len(host.requests) == 1


@pytest.mark.asyncio
async def test_preheader_timeout_is_bounded_and_does_not_resubmit():
    run = request()
    calls = []

    async def handler(req):
        calls.append(req)
        if req.url.path.endswith("/http-runs"):
            await asyncio.Event().wait()
        return httpx.Response(200, json={"accepted": True})

    async with CustomerChannelClient(
        "https://runtime.invalid",
        operation_timeout=0.02,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(CustomerChannelError, match="operation_timeout"):
            async with client.run(run):
                pytest.fail("Headers never arrived")
    assert len(calls) == 2
    assert json.loads(calls[-1].content)["type"] == "run.cancel"


@pytest.mark.asyncio
async def test_cancel_delivery_stalls_but_stream_is_closed_within_cleanup_budget():
    run = request()
    host = Host(Stream([ready()], wait=True))

    async def handler(req):
        if req.url.path.endswith("/messages"):
            await asyncio.Event().wait()
        return await host.handle(req)

    async with CustomerChannelClient(
        "https://runtime.invalid",
        cleanup_timeout=0.025,
        transport=httpx.MockTransport(handler),
    ) as client:
        async with client.run(run) as channel:
            async for _ in channel.events():
                break
        assert host.stream.closed


@pytest.mark.asyncio
async def test_caller_timeout_is_not_mislabelled_as_transport_deadline():
    run = request()
    host = Host(Stream([ready()], wait=True))
    failure = TimeoutError("local caller timeout")
    async with host.client() as client:
        with pytest.raises(TimeoutError) as caught:
            async with client.run(run):
                raise failure
    assert caught.value is failure


@pytest.mark.asyncio
async def test_overlapping_run_and_control_operations_are_rejected():
    run = request()
    host = Host(Stream([ready()], wait=True))
    async with host.client() as client:
        async with client.run(run):
            with pytest.raises(CustomerChannelError, match="run_active"):
                async with client.run(request()):
                    pass
            with pytest.raises(CustomerChannelError, match="run_active"):
                await client.capabilities()
            with pytest.raises(CustomerChannelError, match="run_active"):
                await client.create_session("managed_example", "user-a", "session-a")


@pytest.mark.asyncio
async def test_pending_tool_memory_is_bounded():
    run = request(tools=(tool(),))
    host = Host(
        Stream([ready()] + [call(run, request_id=f"call-{i}") for i in range(65)])
    )
    calls = 0
    async with host.client() as client:
        with pytest.raises(CustomerChannelError, match="too_many_tool_calls"):
            async with client.run(run) as channel:
                async for event in channel.events():
                    calls += event["type"] == "tool.call"
    assert calls == 64


@pytest.mark.asyncio
async def test_response_and_request_limits_apply_before_unbounded_growth():
    host = Host(Stream())
    async with host.client(max_request_bytes=64) as client:
        with pytest.raises(CustomerChannelError, match="request_too_large"):
            async with client.run(request()):
                pass
    assert host.requests == []
    async with host.client(max_event_bytes=5) as client:
        with pytest.raises(CustomerChannelError, match="response_too_large"):
            await client.capabilities()


@pytest.mark.asyncio
async def test_affinity_updates_on_results_and_isolated_across_clients():
    run = request(tools=(tool(),))
    host = Host(Stream([ready(), call(run), complete(run)]))
    async with host.client() as client:
        async with client.run(run) as channel:
            async for event in channel.events():
                if event["type"] == "tool.call":
                    await channel.submit_result("call-a", content={})
        next_run = request()
        host.stream = Stream([ready(), complete(next_run)])
        async with client.run(next_run) as channel:
            async for _ in channel.events():
                pass
    assert host.requests[-1].headers["X-Session-Id"] == "affinity-c"
    async with host.client() as client:
        await client.capabilities()
    assert "X-Session-Id" not in host.requests[-1].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 409, 429, 503])
async def test_start_http_rejection_is_not_replayed_or_cancelled(status):
    calls = []

    async def handler(req):
        calls.append(req)
        return httpx.Response(
            status,
            text="synthetic-private-body",
            headers={"Location": "https://other.invalid"},
        )

    async with CustomerChannelClient(
        "https://runtime.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(CustomerChannelError, match=f"http_status_{status}"):
            async with client.run(request()):
                pass
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_local_http_reverse_result_makes_progress_before_stream_eof():
    """Use real HTTP to catch accidental stream buffering or half-duplex I/O."""
    run = request(tools=(tool(),))
    result_received = asyncio.Event()
    connections = set()
    failures = []

    async def serve(reader, writer):
        task = asyncio.current_task()
        connections.add(task)
        try:
            headers = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
            length = next(
                int(h.split(":", 1)[1])
                for h in headers
                if h.lower().startswith("content-length:")
            )
            body = json.loads(await reader.readexactly(length))
            if headers[0].split()[1].endswith("/http-runs"):
                assert body["catalog_revision"] == run.catalog_revision
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
                )
                for event in (ready(), call(run)):
                    writer.write(("data: " + json.dumps(event) + "\n\n").encode())
                await writer.drain()
                await asyncio.wait_for(result_received.wait(), 2)
                writer.write(("data: " + json.dumps(complete(run)) + "\n\n").encode())
            else:
                assert body["type"] == "tool.result"
                assert body["content"] == {"pages": [1, 2]}
                result_received.set()
                writer.write(
                    b'HTTP/1.1 200 OK\r\nContent-Length: 17\r\nConnection: close\r\n\r\n{"accepted":true}'
                )
            await writer.drain()
        except Exception as error:
            failures.append(type(error).__name__)
        finally:
            writer.close()
            await writer.wait_closed()
            connections.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with (
            server,
            CustomerChannelClient(f"http://127.0.0.1:{port}", turn_timeout=3) as client,
        ):
            async with client.run(run) as channel:
                async for event in channel.events():
                    if event["type"] == "tool.call":
                        await channel.submit_result("call-a", content={"pages": [1, 2]})
    finally:
        if connections:
            await asyncio.gather(*connections)
    assert result_received.is_set()
    assert not failures


@pytest.mark.asyncio
async def test_protocol_success_cannot_hide_error_event_or_pending_tools():
    run = request(tools=(tool(),))
    for middle in (
        call(run),
        {
            "type": "run.event",
            "run_id": run.run_id,
            "event": {"errorCode": "model_unavailable"},
        },
    ):
        host = Host(Stream([ready(), middle, complete(run)]))
        async with host.client() as client:
            with pytest.raises(CustomerChannelError):
                async with client.run(run) as channel:
                    async for _ in channel.events():
                        pass


@pytest.mark.asyncio
async def test_control_request_does_not_race_with_run_or_session_creation():
    entered = asyncio.Event()
    release = asyncio.Event()
    host = Host(Stream())

    async def handler(req):
        entered.set()
        await release.wait()
        return await host.handle(req)

    async with CustomerChannelClient(
        "https://runtime.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        operation = asyncio.create_task(client.capabilities())
        await entered.wait()
        # A broken implementation must fail promptly rather than wait 30 seconds.
        timer = asyncio.get_running_loop().call_later(0.1, release.set)
        try:
            with pytest.raises(CustomerChannelError, match="client_busy"):
                async with client.run(request()):
                    pass
            with pytest.raises(CustomerChannelError, match="client_busy"):
                await client.create_session("managed_example", "user-a", "session-a")
        finally:
            timer.cancel()
            release.set()
            await operation


@pytest.mark.asyncio
async def test_same_client_cannot_cross_user_boundary():
    run = request()
    host = Host(Stream([ready(), complete(run)]))
    async with host.client() as client:
        async with client.run(run) as channel:
            async for _ in channel.events():
                pass
        with pytest.raises(CustomerChannelError, match="session_mismatch"):
            async with client.run(request(user_id="user-b")):
                pass
    assert len(host.requests) == 1
