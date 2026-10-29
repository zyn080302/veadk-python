"""Real Runner cancellation, durable display and exact-owner continuation."""

import asyncio
import threading
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import replace

import pytest
from veadk import Agent
from veadk.runtime.customer import CustomerChannelError
from tests.runtime.customer.test_runtime import IDENTITY, turn
from tests.runtime.customer.test_runtime import setup as _shared_setup

setup = _shared_setup


@pytest.mark.asyncio
async def test_confirmed_cancellation_preserves_identity_history_and_allows_followup(
    setup,
):
    config, host, sessions = setup
    confirmations = []

    async def confirm(context):
        assert host.hosts[0].stream.closed
        confirmations.append(context)
        return True

    # Configure the server hook without requiring its newly added constructor
    # argument, so the same regression reaches the actual pre-fix 409 path.
    object.__setattr__(config, "confirm_cancellation", confirm)
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.wait = True
    pending = asyncio.create_task(
        turn(agent, sessions, invocation_id="cancelled-invocation")
    )
    for _ in range(200):
        if host.hosts:
            break
        await asyncio.sleep(0.005)
    assert host.hosts
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 3)
    host.wait = False
    await turn(agent, sessions, "followup", invocation_id="next-invocation")
    assert len(confirmations) == 1
    context = confirmations[0]
    assert context.local_identity == tuple(IDENTITY.values())
    assert context.invocation_id == "cancelled-invocation"
    assert context.turn.run_id == host.runs[0].run_id
    assert "user-a" not in repr(context) and context.turn.run_id not in repr(context)
    assert [(r.app_name, r.user_id, r.session_id) for r in host.runs] == [
        (
            context.binding.remote_app,
            context.binding.remote_user,
            context.binding.remote_session,
        )
    ] * 2
    saved = await sessions.get_session(**IDENTITY)
    old = [e for e in saved.events if e.invocation_id == context.invocation_id]
    assert [e.content.parts[0].text for e in old if e.author == "user"] == ["hello"]
    assert old[-1].interrupted and old[-1].turn_complete
    assert old[-1].error_code == "customer_turn_cancelled"
    assert not any(
        e.partial or (e.content and any(p.text == "partial" for p in e.content.parts))
        for e in old
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [False, 1, None, "yes"])
async def test_unconfirmed_cancellation_never_releases(setup, answer):
    config, host, sessions = setup

    async def confirm(context):
        return answer

    object.__setattr__(config, "confirm_cancellation", confirm)
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.wait = True
    pending = asyncio.create_task(turn(agent, sessions))
    for _ in range(200):
        if host.hosts:
            break
        await asyncio.sleep(0.005)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
        await turn(agent, sessions)
    assert len(host.runs) == 1


@pytest.mark.asyncio
async def test_confirmed_cancel_during_tool_waits_for_cleanup_and_does_not_replay(
    setup,
):
    from tests.runtime.customer.test_channel import tool

    config, host, sessions = setup
    started, stopped = asyncio.Event(), asyncio.Event()
    calls = []

    async def execute(args, request_id):
        calls.append(request_id)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def confirm(context):
        assert stopped.is_set() and host.hosts[0].stream.closed
        return True

    config = replace(
        config,
        tools=(tool(),),
        executors={"lookup": execute},
        confirm_cancellation=confirm,
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.use_tool = host.wait = True
    task = asyncio.create_task(turn(agent, sessions, invocation_id="tool-cancel"))
    await asyncio.wait_for(started.wait(), 3)
    saved = None
    for _ in range(200):
        saved = await sessions.get_session(**IDENTITY)
        if any(e.get_function_calls() for e in saved.events):
            break
        await asyncio.sleep(0.005)
    assert saved is not None and any(e.get_function_calls() for e in saved.events)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    saved = await sessions.get_session(**IDENTITY)
    calls_seen = [c.id for e in saved.events for c in e.get_function_calls()]
    responses = [r.id for e in saved.events for r in e.get_function_responses()]
    assert calls_seen == responses and len(calls_seen) == 1
    assert saved.events[-1].interrupted
    host.use_tool = host.wait = False
    await turn(agent, sessions, "next")
    assert calls == ["call-a"] and len(host.runs) == 2


@pytest.mark.asyncio
async def test_callback_error_and_persistence_conflict_remain_quarantined(setup):
    config, host, sessions = setup
    from google.adk.events import Event
    from google.genai import types

    async def confirm(context):
        session = await sessions.get_session(**IDENTITY)
        await sessions.append_event(
            session=session,
            event=Event(
                author="foreign_agent",
                invocation_id=context.invocation_id,
                content=types.ModelContent(parts=[types.Part(text="unverified event")]),
            ),
        )
        return True

    config = replace(config, confirm_cancellation=confirm)
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.wait = True
    task = asyncio.create_task(turn(agent, sessions))
    for _ in range(200):
        if host.hosts:
            break
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
        await turn(agent, sessions)
    assert len(host.runs) == 1


@pytest.mark.asyncio
async def test_cancelled_terminal_recovers_only_display_after_save_failure(setup):
    from google.adk.sessions import InMemorySessionService
    from veadk.runtime import get_runtime
    from veadk.runtime.customer.runtime import CustomerRuntime

    config, host, _ = setup

    async def confirm(context):
        return True

    config = replace(config, confirm_cancellation=confirm)

    class Sessions(InMemorySessionService):
        fail = True

        async def append_event(self, session, event):
            if self.fail and event.interrupted:
                raise RuntimeError("synthetic save failure")
            return await super().append_event(session=session, event=event)

    sessions = Sessions()
    await sessions.create_session(
        app_name=IDENTITY["app_name"],
        user_id=IDENTITY["user_id"],
        session_id=IDENTITY["session_id"],
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.wait = True
    task = asyncio.create_task(turn(agent, sessions))
    for _ in range(200):
        if host.hosts:
            break
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    request_count = len(host.requests)
    sessions.fail = False
    runtime = get_runtime("customer")
    assert isinstance(runtime, CustomerRuntime)
    assert await runtime.recover_display(agent, sessions, tuple(IDENTITY.values())) == 1
    assert len(host.requests) == request_count
    host.wait = False
    await turn(agent, sessions, "continuation")
    assert len(host.runs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_commit", "during_commit", "after_commit"])
async def test_cancel_during_response_journal_preserves_committed_history(
    setup, monkeypatch, phase
):
    from veadk.runtime.customer.session_store import CustomerSessionLease
    from tests.runtime.customer.test_channel import tool

    config, host, sessions = setup
    boundary, stopped = asyncio.Event(), asyncio.Event()
    finish_write = asyncio.Event()
    release_commit = threading.Event()
    response_write = ContextVar("response_journal_write", default=False)
    executions = []

    async def execute(arguments, request_id):
        executions.append(request_id)
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    original_transaction = config.store._transaction

    @asynccontextmanager
    async def transaction(**kwargs):
        async with original_transaction(**kwargs) as connection:
            yield connection
            if response_write.get() and phase == "before_commit":
                boundary.set()
                await finish_write.wait()

    monkeypatch.setattr(config.store, "_transaction", transaction)
    if phase == "during_commit":
        from aiosqlite import Connection

        original_execute = Connection._execute
        loop = asyncio.get_running_loop()

        async def execute_database(connection, function, *args, **kwargs):
            if response_write.get() and getattr(function, "__name__", "") == "commit":

                def commit():
                    loop.call_soon_threadsafe(boundary.set)
                    assert release_commit.wait(2)
                    return function(*args, **kwargs)

                return await original_execute(connection, commit)
            return await original_execute(connection, function, *args, **kwargs)

        monkeypatch.setattr(Connection, "_execute", execute_database)
    original_append = CustomerSessionLease.append_event

    async def append(lease, event):
        if not event.get_function_responses() or boundary.is_set():
            return await original_append(lease, event)
        token = response_write.set(True)
        try:
            await original_append(lease, event)
            if phase == "after_commit":
                boundary.set()
                await finish_write.wait()
        finally:
            response_write.reset(token)

    monkeypatch.setattr(CustomerSessionLease, "append_event", append)

    async def confirm(context):
        assert stopped.is_set() and host.hosts[0].stream.closed
        return True

    config = replace(
        config,
        tools=(tool(),),
        executors={"lookup": execute},
        confirm_cancellation=confirm,
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.use_tool = host.wait = True
    task = asyncio.create_task(turn(agent, sessions, invocation_id="journal-cancel"))
    await asyncio.wait_for(boundary.wait(), 3)
    task.cancel()
    asyncio.get_running_loop().call_later(0.05, finish_write.set)
    if phase == "during_commit":
        asyncio.get_running_loop().call_later(0.05, release_commit.set)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 4)
    # Do not hold the cancellation-generated response at the test boundary.
    monkeypatch.setattr(CustomerSessionLease, "append_event", original_append)
    saved = await sessions.get_session(**IDENTITY)
    calls = [c.id for e in saved.events for c in e.get_function_calls()]
    replies = [r for e in saved.events for r in e.get_function_responses()]
    assert len(calls) == 1 and calls == [r.id for r in replies]
    assert saved.events[-1].interrupted and saved.events[-1].turn_complete
    assert replies[0].response == {"pages": [1, 2]}
    host.use_tool = host.wait = False
    await asyncio.wait_for(turn(agent, sessions, "continue"), 3)
    assert executions == ["call-a"] and len(host.runs) == 2


@pytest.mark.asyncio
async def test_cancelled_runner_does_not_wait_for_unconsumable_cleanup_error(
    setup, monkeypatch
):
    from veadk.runtime.customer.session_store import CustomerSessionLease

    config, host, sessions = setup

    async def unavailable(lease):
        raise CustomerChannelError("store_unavailable")

    monkeypatch.setattr(CustomerSessionLease, "_close", unavailable)
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.wait = True
    task = asyncio.create_task(turn(agent, sessions))
    for _ in range(200):
        if host.hosts:
            break
        await asyncio.sleep(0.005)
    assert host.hosts
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=1)
    if task not in done:
        # A failing pre-fix run must not leave its deadlocked Runner behind.
        task.cancel()
        await asyncio.wait({task}, timeout=1)
    assert task in done, "Cancellation was replaced by an unconsumable error event"
    with pytest.raises(asyncio.CancelledError):
        task.result()
    assert host.hosts[0].stream.closed
    from sqlalchemy import select
    from veadk.runtime.customer.session_store import _key, _sessions

    async with config.store._engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    select(_sessions).where(
                        _sessions.c.key == _key(tuple(IDENTITY.values()))
                    )
                )
            )
            .mappings()
            .one()
        )
    assert row["owner"] and row["status"] == "running"
    with pytest.raises(CustomerChannelError, match="^session_busy$"):
        await turn(agent, sessions, "continue")
    assert len(host.runs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body_error", [False, True])
async def test_non_cancelled_lease_exit_still_reports_cleanup_failure(
    setup, monkeypatch, body_error
):
    from veadk.runtime.customer.session_store import CustomerSessionLease

    config, _, _ = setup
    lease = await config.store.claim(
        tuple(IDENTITY.values()),
        engine_id=config._binding_id,
        remote_app=config.remote_app,
        lease_seconds=10,
    )

    async def unavailable(lease):
        raise CustomerChannelError("store_unavailable")

    monkeypatch.setattr(CustomerSessionLease, "_close", unavailable)
    with pytest.raises(CustomerChannelError, match="^store_unavailable$"):
        async with lease:
            if body_error:
                raise ValueError("synthetic body error")
    assert not lease._closed


@pytest.mark.asyncio
async def test_unfinished_journal_writer_never_authorizes_cancellation_settlement(
    setup, monkeypatch
):
    from veadk.runtime.customer.session_store import CustomerSessionLease
    from tests.runtime.customer.test_channel import tool

    config, host, sessions = setup
    writing, release = asyncio.Event(), asyncio.Event()
    writers, confirmations = [], []
    original_append = CustomerSessionLease.append_event

    async def append(lease, event):
        if event.get_function_responses():
            writers.append(asyncio.current_task())
            writing.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        await original_append(lease, event)

    monkeypatch.setattr(CustomerSessionLease, "append_event", append)

    async def execute(arguments, request_id):
        await asyncio.Event().wait()

    async def confirm(context):
        confirmations.append(context)
        return True

    config = replace(
        config,
        tools=(tool(),),
        executors={"lookup": execute},
        confirm_cancellation=confirm,
        cleanup_timeout=0.1,
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.use_tool = host.wait = True
    task = asyncio.create_task(turn(agent, sessions))
    try:
        await asyncio.wait_for(writing.wait(), 3)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert task in done
        with pytest.raises(asyncio.CancelledError):
            task.result()
        assert not confirmations and host.hosts[0].stream.closed
        with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
            await turn(agent, sessions, "continue")
        assert len(host.runs) == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.wait({task, *writers}, timeout=2)
    assert all(writer.done() for writer in writers)
    saved = await sessions.get_session(**IDENTITY)
    assert not any(e.get_function_responses() or e.interrupted for e in saved.events)
