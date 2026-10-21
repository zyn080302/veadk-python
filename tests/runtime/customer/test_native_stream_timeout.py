"""Real loopback HTTP regressions for native stream deadline ownership."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from veadk.runtime.customer import (
    CustomerChannelClient,
    CustomerChannelError,
    CustomerToolDispatcher,
)
from tests.runtime.customer.test_channel import tool
from tests.runtime.customer.test_native_channel import NativeHost, request


class SocketHost(NativeHost):
    """Keep real socket timing while reusing the native protocol fixture."""

    def __init__(self, batches=(), *, delay=0.3, phase="body", delayed_step=1):
        super().__init__(batches)
        self.socket_delay = delay
        self.phase = phase
        self.delayed_step = delayed_step
        self.headers_sent = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.handlers = set()
        self.errors = []

    async def serve(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("ascii").split("\r\n")
            method, path, _ = lines[0].split()
            headers = dict(line.split(":", 1) for line in lines[1:] if line)
            body = await reader.readexactly(int(headers.get("Content-Length", 0)))
            response = await self.handle(
                httpx.Request(method, "http://localhost" + path, content=body)
            )
            data = await response.aread()
            delay = (
                self.socket_delay
                if self.delayed_step is None or len(self.requests) == self.delayed_step
                else 0
            )
            if self.phase == "headers":
                await asyncio.sleep(delay)
            response_head = (
                f"HTTP/1.1 {response.status_code} OK\r\n"
                f"Content-Type: {response.headers.get('content-type')}\r\n"
                f"Content-Length: {len(data)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            if self.phase == "partial_headers":
                writer.write(response_head[:10])
                await writer.drain()
                await asyncio.sleep(delay)
                response_head = response_head[10:]
            writer.write(response_head)
            await writer.drain()
            self.headers_sent.set()
            if self.phase == "gap":
                middle = max(1, len(data) // 2)
                writer.write(data[:middle])
                await writer.drain()
                data = data[middle:]
            if self.phase in ("body", "gap"):
                # Detect actual client closure, including cancellation/timeouts.
                try:
                    assert await asyncio.wait_for(reader.read(1), delay) == b""
                    self.disconnected.set()
                    return
                except TimeoutError:
                    pass
            writer.write(data)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            self.disconnected.set()
        except Exception as error:
            self.errors.append(type(error).__name__)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except ConnectionError:
                pass
            finally:
                self.handlers.discard(task)

    @asynccontextmanager
    async def running(self):
        server = await asyncio.start_server(self.serve, "127.0.0.1", 0)
        try:
            yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        finally:
            server.close()
            await server.wait_closed()
            tasks = tuple(self.handlers)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            assert not self.errors


async def collect(client, host, output):
    run = request(tools=(tool(),)) if host.batches else request()
    dispatch = CustomerToolDispatcher(
        client, run, {"lookup": host.execute} if run.tools else {}
    )
    try:
        async with dispatch:
            async for value in dispatch.events():
                output.append(value)
    finally:
        assert dispatch.quiescent


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["body", "gap"])
async def test_native_body_can_exceed_short_operation_deadline(phase):
    host = SocketHost(phase=phase)
    output = []
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=2
        ) as client:
            await collect(client, host, output)
    assert output[-1]["type"] == "run.completed"
    assert output[-2]["event"]["content"]["parts"] == [{"text": "answer"}]
    assert len(host.requests) == 1


@pytest.mark.asyncio
async def test_delayed_tool_echo_is_verified_once_before_final():
    host = SocketHost((1,), delayed_step=2)
    output = []
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=2
        ) as client:
            await collect(client, host, output)
    assert output[-1]["type"] == "run.completed"
    assert len(host.requests) == 2
    assert len(host.executed) == len(host.results) == 1
    assert host.results[0]["parts"][0]["functionResponse"]["id"] == host.executed[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["headers", "partial_headers"])
async def test_slow_response_headers_still_use_operation_deadline(phase):
    host = SocketHost(phase=phase)
    output = []
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=2
        ) as client:
            with pytest.raises(CustomerChannelError, match="operation_timeout"):
                await collect(client, host, output)
    assert len(host.requests) == 1 and not output


@pytest.mark.asyncio
async def test_total_deadline_is_not_reset_after_tool_continuation():
    host = SocketHost((1,), delay=0.3, delayed_step=None)
    output = []
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=0.5
        ) as client:
            with pytest.raises(CustomerChannelError, match="run_timeout"):
                await collect(client, host, output)
            await asyncio.wait_for(host.disconnected.wait(), 1)
    assert len(host.requests) == 2
    assert len(host.executed) == len(host.results) == 1
    assert not any(value["type"] == "run.completed" for value in output)


@pytest.mark.asyncio
async def test_delayed_wrong_echo_is_rejected_without_replay():
    host = SocketHost((1,), delayed_step=2)

    def change_echo(events):
        if events[0]["author"] == "user":
            events[0]["content"]["parts"][0]["functionResponse"]["id"] = "wrong-id"

    host.mutation = change_echo
    output = []
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=2
        ) as client:
            with pytest.raises(CustomerChannelError, match="result_not_accepted"):
                await collect(client, host, output)
    assert len(host.requests) == 2
    assert len(host.executed) == len(host.results) == 1
    assert not any(value["type"] == "run.completed" for value in output)


@pytest.mark.asyncio
async def test_control_response_body_keeps_short_operation_deadline():
    host = SocketHost()
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=2
        ) as client:
            with pytest.raises(CustomerChannelError, match="operation_timeout"):
                await client.create_session("fixture", "user", "session")
            await asyncio.wait_for(host.disconnected.wait(), 1)
    assert len(host.requests) == 1


@pytest.mark.asyncio
async def test_turn_deadline_closes_waiting_body_without_replay():
    host = SocketHost(delay=2)
    output = []
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=0.4
        ) as client:
            with pytest.raises(CustomerChannelError, match="run_timeout"):
                await collect(client, host, output)
            await asyncio.wait_for(host.disconnected.wait(), 1)
    assert len(host.requests) == 1 and not output


@pytest.mark.asyncio
async def test_caller_cancellation_closes_waiting_body_without_replay():
    host = SocketHost(delay=2)
    output = []
    async with host.running() as endpoint:
        async with CustomerChannelClient(
            endpoint, protocol="native", operation_timeout=0.1, turn_timeout=3
        ) as client:
            task = asyncio.create_task(collect(client, host, output))
            try:
                await asyncio.wait_for(host.headers_sent.wait(), 1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await asyncio.wait_for(host.disconnected.wait(), 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert len(host.requests) == 1 and not output
