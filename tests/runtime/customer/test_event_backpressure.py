"""Lossless bounded publication through real dispatcher, ADK and Runtime paths."""

import asyncio
from contextlib import aclosing
from dataclasses import replace

import pytest

from veadk.runtime.customer import CustomerChannelError, CustomerToolDispatcher
from veadk.runtime.customer.dispatch import _LocalToolFailure
from tests.runtime.customer.test_channel import call, complete, request, tool
from tests.runtime.customer.test_dispatch import Host
from tests.runtime.customer.test_events import adapter, native, wire
from tests.runtime.customer.test_native_tools import NativeHost, agent_for
from tests.runtime.customer.test_runtime import IDENTITY, setup as runtime_setup, turn

setup = runtime_setup


async def wait_until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), 1)


def burst(run, count=40):
    return [wire(run, native(text=str(i), partial=True)) for i in range(count)]


@pytest.mark.asyncio
async def test_short_slow_consumer_preserves_every_event_and_terminal():
    run = request()
    host = Host(run, [*burst(run), complete(run)])
    seen, high_water = [], 0
    async with host.client(turn_timeout=2) as client:
        dispatch = CustomerToolDispatcher(client, run, {}, event_queue_size=2)
        async with dispatch:
            await wait_until(dispatch._queue.full)
            await asyncio.sleep(0.02)
            assert not dispatch._owner.done(), "transient capacity must not abort"
            async for event in dispatch.events():
                high_water = max(high_water, dispatch._queue.qsize())
                seen.append(event)
                await asyncio.sleep(0.001)
        assert dispatch.quiescent
    assert high_water <= 2 and dispatch._queue.maxsize == 2
    assert [
        e["event"]["content"]["parts"][0]["text"]
        for e in seen
        if e["type"] == "run.event"
    ] == [str(i) for i in range(40)]
    assert seen[-1] == complete(run)
    assert sum(e["type"] == "run.completed" for e in seen) == 1
    assert host.cancelled == 0 and host.stream.closed


@pytest.mark.asyncio
async def test_adk_partials_reach_slow_consumer_before_host_terminal():
    run = request()
    host = Host(run, burst(run, 12))
    seen = []
    async with host.client(turn_timeout=2) as client:
        dispatch = CustomerToolDispatcher(client, run, {}, event_queue_size=1)
        async with adapter(dispatch) as stream:
            await wait_until(dispatch._queue.full)
            await asyncio.sleep(0.02)
            async for event in stream.events():
                seen.append(event)
                if len(seen) == 1:
                    assert event.partial and not event.turn_complete
                    assert not host.stream.closed
                    host.send(
                        wire(
                            run,
                            native(
                                text="complete",
                                usage_metadata={
                                    "prompt_token_count": 3,
                                    "candidates_token_count": 4,
                                    "total_token_count": 7,
                                },
                            ),
                        )
                    )
                    host.send(complete(run))
                await asyncio.sleep(0.001)
        assert dispatch.quiescent
    assert [e.content.parts[0].text for e in seen] == [*map(str, range(12)), "complete"]
    assert seen[-1].turn_complete and seen[-1].usage_metadata.total_token_count == 7
    assert host.cancelled == 0


@pytest.mark.asyncio
async def test_native_batches_wait_for_durable_consumer_without_accepted_deadlock(
    setup,
    monkeypatch,
):
    from veadk.runtime.customer.session_store import CustomerSessionLease

    config, _, sessions = setup
    host = NativeHost()
    host.count = 12
    invoked, persisted = [], []
    original = CustomerSessionLease.append_event

    async def slow_journal(self, event):
        await asyncio.sleep(0.003)
        await original(self, event)
        persisted.extend(r.id for r in event.get_function_responses())

    monkeypatch.setattr(CustomerSessionLease, "append_event", slow_journal)

    async def lookup(name: str) -> dict:
        invoked.append(name)
        return {"name": name}

    agent = agent_for(replace(config, event_queue_size=1), lookup, host)
    events = await asyncio.wait_for(turn(agent, sessions), 4)
    calls = [c for e in events for c in e.get_function_calls()]
    responses = [r for e in events for r in e.get_function_responses()]
    assert len(invoked) == len(calls) == len(responses) == len(persisted) == 12
    assert {r.id for r in responses} == {c.id for c in calls} == set(persisted)
    assert len(host.hosts[0].results) == 12
    assert host.hosts[0].cancelled == 0 and host.hosts[0].stream.closed
    assert events[-1].turn_complete
    saved = await sessions.get_session(**IDENTITY)
    assert len([r for e in saved.events for r in e.get_function_responses()]) == 12


@pytest.mark.asyncio
async def test_stalled_full_queue_expires_at_existing_turn_deadline():
    run = request()
    host = Host(run, burst(run))
    async with host.client(turn_timeout=0.04) as client:
        dispatch = CustomerToolDispatcher(client, run, {}, event_queue_size=1)
        with pytest.raises(CustomerChannelError, match="^run_timeout$"):
            async with dispatch:
                await wait_until(dispatch._queue.full)
                await asyncio.sleep(0.08)
                async for _ in dispatch.events():
                    pass
        assert dispatch.quiescent and dispatch._queue.qsize() <= 1
    assert host.cancelled == 1 and host.stream.closed


@pytest.mark.asyncio
async def test_iterator_close_reaps_a_producer_blocked_on_full_queue():
    run = request()
    host = Host(run, burst(run))
    async with host.client(turn_timeout=2) as client:
        dispatch = CustomerToolDispatcher(client, run, {}, event_queue_size=1)
        async with dispatch:
            events = dispatch.events()
            assert (await anext(events))["type"] == "channel.ready"
            await wait_until(dispatch._queue.full)
            await asyncio.sleep(0.02)
            await asyncio.wait_for(events.aclose(), 0.5)
            assert dispatch.quiescent and dispatch._owner.cancelled()
        assert dispatch._queue.qsize() <= 1
    assert host.cancelled == 1 and host.stream.closed


@pytest.mark.asyncio
async def test_caller_cancel_reaps_full_queue_and_never_submits_late_result():
    run = request(tools=(tool(),))
    host = Host(run, [call(run), *burst(run)])
    started, stopped, hold = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def executor(args, call_id):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with host.client(turn_timeout=2) as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, event_queue_size=1
        )

        async def consume():
            async with dispatch:
                async with aclosing(dispatch.events()) as events:
                    async for event in events:
                        if event["type"] == "tool.call":
                            await hold.wait()

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(started.wait(), 1)
            await wait_until(dispatch._queue.full)
            await asyncio.sleep(0.02)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            assert stopped.is_set() and dispatch.quiescent
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert not host.results and host.cancelled == 1


@pytest.mark.asyncio
async def test_failure_remains_observable_even_when_data_queue_is_full():
    run = request(tools=(tool(),))
    host = Host(run, [call(run), *burst(run)])
    started, fail = asyncio.Event(), asyncio.Event()

    async def executor(args, call_id):
        started.set()
        await fail.wait()
        raise _LocalToolFailure("fixture_publication_failed")

    async with host.client(turn_timeout=2) as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, event_queue_size=2
        )
        with pytest.raises(CustomerChannelError, match="^fixture_publication_failed$"):
            async with dispatch:
                await asyncio.wait_for(started.wait(), 1)
                await wait_until(dispatch._queue.full)
                fail.set()
                await wait_until(dispatch._owner.done)
                async for _ in dispatch.events():
                    pass
        assert dispatch.quiescent
    assert not host.results and host.cancelled == 1
