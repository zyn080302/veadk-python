"""Execution and cancellation contracts using synthetic Shared HTTP streams."""

import asyncio
import json
from contextvars import ContextVar

import httpx
import pytest

from veadk.runtime.customer import CustomerChannelError, CustomerToolDispatcher
from tests.runtime.customer.test_channel import call, complete, ready, request, tool


class Stream(httpx.AsyncByteStream):
    def __init__(self, events):
        self.queue = asyncio.Queue()
        for event in events:
            self.queue.put_nowait(event)
        self.closed = False

    async def __aiter__(self):
        while True:
            event = await self.queue.get()
            yield ("data: " + json.dumps(event) + "\n\n").encode()

    async def aclose(self):
        self.closed = True


class Host:
    def __init__(self, run, events):
        self.run = run
        self.stream = Stream([ready(), *events])
        self.requests = []
        self.results = []
        self.result_handler = None
        self.cancelled = 0

    async def handle(self, req):
        self.requests.append(req)
        if req.url.path.endswith("/http-runs"):
            return httpx.Response(
                200,
                stream=self.stream,
                headers={
                    "content-type": "text/event-stream",
                },
            )
        message = json.loads(req.content)
        if message["type"] == "run.cancel":
            self.cancelled += 1
        else:
            self.results.append(message)
            if self.result_handler:
                return await self.result_handler(message)
        return httpx.Response(200, json={"accepted": True})

    def client(self, **kwargs):
        from veadk.runtime.customer import CustomerChannelClient

        return CustomerChannelClient(
            "https://runtime.invalid",
            transport=httpx.MockTransport(self.handle),
            **kwargs,
        )

    def send(self, event):
        self.stream.queue.put_nowait(event)


async def consume(dispatch):
    async with dispatch:
        return [event async for event in dispatch.events()]


async def lookup(arguments, call_id):
    return {"name": arguments["name"], "call_id": call_id}


@pytest.mark.asyncio
async def test_executes_tool_and_preserves_invocation_context():
    identity = ContextVar("synthetic_identity")
    identity.set("user-a")
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    seen = []

    async def executor(args, call_id):
        seen.append((identity.get(), args, call_id))
        return {"ok": True}

    async def ack(_):
        host.send(complete(run))
        return httpx.Response(200, json={"accepted": True})

    host.result_handler = ack
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
        events = await consume(dispatch)
        assert dispatch.quiescent
    assert seen == [("user-a", {"name": "企业"}, "call-a")]
    assert len(host.results) == 1
    assert events[-1]["type"] == "run.completed"
    assert host.stream.closed and not host.cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "executors", [{}, {"lookup": lookup, "extra": lookup}, {"lookup": lambda a, b: {}}]
)
async def test_invalid_executor_catalog_fails_before_http(executors):
    run = request(tools=(tool(),))
    host = Host(run, [])
    async with host.client() as client:
        with pytest.raises(ValueError):
            CustomerToolDispatcher(client, run, executors)
    assert not host.requests


@pytest.mark.asyncio
async def test_parallel_calls_respect_limit_and_wait_for_submissions():
    run = request(tools=(tool(),))
    host = Host(run, [call(run, request_id=f"call-{i}") for i in range(6)])
    release = asyncio.Event()
    reached = asyncio.Event()
    active = 0
    peak = 0

    async def executor(args, call_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            reached.set()
        try:
            await release.wait()
            return {}
        finally:
            active -= 1

    async def ack(_):
        if len(host.results) == 6:
            host.send(complete(run))
        return httpx.Response(200, json={"accepted": True})

    host.result_handler = ack
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, max_concurrency=2
        )
        task = asyncio.create_task(consume(dispatch))
        await asyncio.wait_for(reached.wait(), 1)
        assert active == 2
        release.set()
        events = await asyncio.wait_for(task, 2)
    assert peak == 2 and len(host.results) == 6 and active == 0
    assert events[-1]["type"] == "run.completed"
    assert dispatch.quiescent


@pytest.mark.asyncio
async def test_cancel_is_received_while_tool_runs_and_late_return_is_discarded():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def executor(args, call_id):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            return {"late": True}

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
        task = asyncio.create_task(consume(dispatch))
        await asyncio.wait_for(started.wait(), 1)
        host.send({"type": "tool.cancel", "run_id": run.run_id, "request_id": "call-a"})
        await asyncio.wait_for(cancelled.wait(), 1)
        host.send(complete(run))
        await asyncio.wait_for(task, 1)
    assert not host.results and dispatch.quiescent


@pytest.mark.asyncio
async def test_failed_ack_overrides_early_host_success():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    terminal_read = asyncio.Event()

    async def ack(_):
        host.send(complete(run))
        await asyncio.sleep(0.02)
        terminal_read.set()
        return httpx.Response(503, json={"ignored": "synthetic-only"})

    host.result_handler = ack
    events = []
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": lookup})
        with pytest.raises(CustomerChannelError, match="http_status_503"):
            async with dispatch:
                async for event in dispatch.events():
                    events.append(event)
    assert terminal_read.is_set()
    assert all(e["type"] != "run.completed" for e in events)
    assert len(host.results) == 1 and dispatch.quiescent


@pytest.mark.asyncio
async def test_tool_error_does_not_expose_exception_text():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])

    async def executor(args, call_id):
        raise ValueError("synthetic-sensitive-exception")

    async def ack(_):
        host.send(complete(run))
        return httpx.Response(200, json={"accepted": True})

    host.result_handler = ack
    async with host.client() as client:
        await consume(CustomerToolDispatcher(client, run, {"lookup": executor}))
    assert host.results[0]["status"] == "error"
    assert host.results[0]["error"] == "tool_execution_failed"
    assert "synthetic-sensitive-exception" not in json.dumps(host.results)


@pytest.mark.asyncio
async def test_queue_time_counts_against_tool_deadline():
    run = request(tools=(tool(),))
    host = Host(run, [call(run), call(run, request_id="call-b", deadline_ms=30)])
    invoked = []

    async def executor(args, call_id):
        invoked.append(call_id)
        await asyncio.Event().wait()

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, max_concurrency=1
        )
        with pytest.raises(CustomerChannelError, match="tool_timeout"):
            await consume(dispatch)
    assert invoked == ["call-a"] and not host.results
    assert host.cancelled == 1 and dispatch.quiescent


@pytest.mark.asyncio
async def test_slow_consumer_has_bounded_buffer_and_cancels_host():
    run = request()
    host = Host(
        run,
        [
            {
                "type": "run.event",
                "run_id": run.run_id,
                "event": {"content": {"parts": [{"text": str(i)}]}},
            }
            for i in range(40)
        ],
    )
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {}, event_queue_size=2)
        with pytest.raises(CustomerChannelError, match="event_backpressure"):
            async with dispatch:
                await asyncio.sleep(0.05)
                async for _ in dispatch.events():
                    pass
    assert dispatch.quiescent and host.cancelled == 1 and host.stream.closed


@pytest.mark.asyncio
async def test_consumer_cancel_reaps_tools_and_client_can_send_again():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def executor(args, call_id):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
        task = asyncio.create_task(consume(dispatch))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and dispatch.quiescent and not host.results
        next_run = request()
        host.stream = Stream([ready(), complete(next_run)])
        events = await consume(CustomerToolDispatcher(client, next_run, {}))
        assert events[-1]["type"] == "run.completed"
    assert host.cancelled == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_concurrency": 0},
        {"max_concurrency": 65},
        {"max_concurrency": True},
        {"event_queue_size": 0},
        {"event_queue_size": 257},
        {"cleanup_timeout": 0},
        {"cleanup_timeout": float("nan")},
        {"cleanup_timeout": float("inf")},
        {"cleanup_timeout": True},
    ],
)
async def test_invalid_budgets_fail_before_http(kwargs):
    run = request()
    host = Host(run, [])
    async with host.client() as client:
        with pytest.raises(ValueError):
            CustomerToolDispatcher(client, run, {}, **kwargs)
    assert not host.requests


@pytest.mark.asyncio
async def test_one_reader_one_run_and_early_exit():
    run = request()
    host = Host(run, [])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        with pytest.raises(CustomerChannelError, match="dispatcher_unavailable"):
            await anext(dispatch.events())
        async with dispatch:
            stream = dispatch.events()
            assert (await anext(stream))["type"] == "channel.ready"
            with pytest.raises(CustomerChannelError, match="dispatcher_unavailable"):
                await anext(dispatch.events())
            await stream.aclose()
        assert dispatch.quiescent
        with pytest.raises(CustomerChannelError, match="dispatcher_unavailable"):
            await dispatch.__aenter__()
    assert host.cancelled == 1


@pytest.mark.asyncio
async def test_unexpected_executor_cancellation_is_failure():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])

    async def executor(args, call_id):
        raise asyncio.CancelledError()

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
        with pytest.raises(CustomerChannelError, match="executor_cancelled"):
            await consume(dispatch)
    assert not host.results and host.cancelled == 1 and dispatch.quiescent


@pytest.mark.asyncio
async def test_consumer_error_keeps_original_exception():
    run = request()
    host = Host(run, [])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        with pytest.raises(ValueError, match="consumer failure"):
            async with dispatch:
                async for _ in dispatch.events():
                    raise ValueError("consumer failure")
    assert host.cancelled == 1 and dispatch.quiescent


@pytest.mark.asyncio
async def test_whole_turn_deadline_cleans_up_active_tools():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    stopped = asyncio.Event()

    async def executor(args, call_id):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with host.client(turn_timeout=0.03) as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
        with pytest.raises(CustomerChannelError, match="run_timeout"):
            await consume(dispatch)
    assert stopped.is_set() and dispatch.quiescent and host.cancelled == 1


@pytest.mark.asyncio
async def test_noncooperative_tool_has_bounded_exit_no_late_result():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def executor(args, call_id):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return {"late": True}

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, cleanup_timeout=0.08
        )
        task = asyncio.create_task(consume(dispatch))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        try:
            with pytest.raises(CustomerChannelError, match="cleanup_timeout"):
                await asyncio.wait_for(task, 0.5)
            assert cancelled.is_set() and not dispatch.quiescent
        finally:
            release.set()
            # Explicitly join the quarantined dispatcher before client reuse/close.
            with pytest.raises(CustomerChannelError, match="cleanup_timeout"):
                await dispatch.aclose()
        assert dispatch.quiescent and not host.results


@pytest.mark.asyncio
async def test_snapshot_and_observer_mutation_cannot_change_execution():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    seen = []

    async def executor(args, call_id):
        await asyncio.sleep(0.01)
        seen.append(args["name"])
        return {}

    async def ack(_):
        host.send(complete(run))
        return httpx.Response(200, json={"accepted": True})

    host.result_handler = ack
    executors = {"lookup": executor}
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, executors)
        executors.clear()
        run.new_message["parts"][0]["text"] = "mutated"
        async with dispatch:
            async for event in dispatch.events():
                if event["type"] == "tool.call":
                    event["arguments"]["name"] = "mutated"
    assert seen == ["企业"]
    assert (
        json.loads(host.requests[0].content)["payload"]["new_message"]["parts"][0][
            "text"
        ]
        == "查询企业"
    )


@pytest.mark.asyncio
async def test_cancelled_queued_tool_never_invokes_executor():
    run = request(tools=(tool(),))
    host = Host(
        run,
        [
            call(run),
            call(run, request_id="call-b"),
            {"type": "tool.cancel", "run_id": run.run_id, "request_id": "call-b"},
        ],
    )
    release = asyncio.Event()
    invoked = []

    async def executor(args, call_id):
        invoked.append(call_id)
        await release.wait()
        return {}

    async def ack(_):
        host.send(complete(run))
        return httpx.Response(200, json={"accepted": True})

    host.result_handler = ack
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, max_concurrency=1
        )
        async with dispatch:
            async for event in dispatch.events():
                if event["type"] == "tool.cancel":
                    release.set()
    assert invoked == ["call-a"] and len(host.results) == 1 and dispatch.quiescent


@pytest.mark.asyncio
async def test_error_terminal_cancels_active_tool():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def executor(args, call_id):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
        task = asyncio.create_task(consume(dispatch))
        await asyncio.wait_for(started.wait(), 1)
        host.send(complete(run, "error"))
        with pytest.raises(CustomerChannelError, match="run_error"):
            await task
    assert stopped.is_set() and not host.results and dispatch.quiescent


@pytest.mark.asyncio
async def test_duplicate_cancellation_does_not_interrupt_cleanup_twice():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()
    cancellations = 0

    async def executor(args, call_id):
        nonlocal cancellations
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellations += 1
            cleaning.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancellations += 1
            return {}

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
        task = asyncio.create_task(consume(dispatch))
        await asyncio.wait_for(started.wait(), 1)
        cancel = {"type": "tool.cancel", "run_id": run.run_id, "request_id": "call-a"}
        host.send(cancel)
        await asyncio.wait_for(cleaning.wait(), 1)
        host.send(cancel)
        await asyncio.sleep(0.01)
        release.set()
        host.send(complete(run))
        await asyncio.wait_for(task, 1)
    assert cancellations == 1 and not host.results and dispatch.quiescent


@pytest.mark.asyncio
async def test_failure_and_context_exit_share_one_cleanup_deadline():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started = asyncio.Event()
    release = asyncio.Event()

    async def executor(args, call_id):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return {}

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, cleanup_timeout=0.2
        )
        task = asyncio.create_task(consume(dispatch))
        await asyncio.wait_for(started.wait(), 1)
        began = asyncio.get_running_loop().time()
        host.send(complete(run, "error"))
        try:
            with pytest.raises(CustomerChannelError, match="cleanup_timeout"):
                await task
            # Joining children and context exit must share the 0.2 s budget.
            assert asyncio.get_running_loop().time() - began < 0.28
        finally:
            release.set()
            await asyncio.sleep(0.01)
        assert dispatch.quiescent and not host.results
