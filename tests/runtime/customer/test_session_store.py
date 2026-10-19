"""Durable ownership across independent connections; no remote execution."""

import asyncio
import hashlib

import pytest
import pytest_asyncio
from google.adk.events import Event
from google.genai import types
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from veadk.runtime.customer import CustomerChannelError, CustomerSessionStore


IDENTITY = ("local-app", "user-a", "session-a")
DIGEST = hashlib.sha256(b"synthetic input").hexdigest()


def final(text="answer", **kwargs):
    return Event(
        author="local_agent",
        invocation_id="invocation-a",
        content=types.ModelContent(parts=[types.Part(text=text)]),
        turn_complete=True,
        **kwargs,
    )


async def claim(store, identity=IDENTITY, **kwargs):
    return await store.claim(
        identity, engine_id="customer-v1", remote_app="managed_example", **kwargs
    )


@pytest_asyncio.fixture
async def stores(tmp_path):
    url = "sqlite+aiosqlite:///" + str(tmp_path / "sessions.db")
    engines = [create_async_engine(url, hide_parameters=True) for _ in range(2)]
    result = [CustomerSessionStore(e) for e in engines]
    await result[0].initialize()
    try:
        yield result
    finally:
        for engine in engines:
            await engine.dispose()


@pytest.mark.asyncio
async def test_two_connections_have_one_owner(stores):
    results = await asyncio.gather(*(claim(s) for s in stores), return_exceptions=True)
    owners = [r for r in results if not isinstance(r, BaseException)]
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(owners) == len(errors) == 1
    assert str(errors[0]) == "session_busy"
    async with owners[0] as lease:
        binding = lease.binding
        assert binding.remote_app == "managed_example"
        assert binding.remote_user != IDENTITY[1]
        assert binding.remote_session != IDENTITY[2]
        assert "user-a" not in repr(lease) + repr(binding)
    async with await claim(stores[1]) as later:
        assert later.binding == binding


@pytest.mark.asyncio
async def test_identity_and_engine_binding(stores):
    async with await claim(stores[0]) as first:
        async with await claim(
            stores[1], ("local-app", "user-b", "session-a")
        ) as second:
            assert first.binding != second.binding
    for options in (
        dict(engine_id="another", remote_app="managed_example"),
        dict(engine_id="customer-v1", remote_app="managed_other"),
    ):
        with pytest.raises(CustomerChannelError, match="^engine_mismatch$"):
            await stores[0].claim(IDENTITY, **options)


@pytest.mark.asyncio
async def test_reserve_duplicate_and_uncertain_execution(stores):
    async with await claim(stores[0]) as lease:
        turn = await lease.begin_turn("invocation-a", DIGEST)
        assert len({turn.run_id, turn.channel_id, turn.scope_id}) == 3
        with pytest.raises(CustomerChannelError, match="^duplicate_turn$"):
            await lease.begin_turn("invocation-a", DIGEST)
        with pytest.raises(CustomerChannelError, match="^invocation_conflict$"):
            await lease.begin_turn("invocation-a", "0" * 64)
    with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
        await claim(stores[1])


@pytest.mark.asyncio
async def test_restart_recovers_display_without_resubmitting(stores):
    answer = final()
    answer.actions.state_delta = {"answer": "answer"}
    async with await claim(stores[0]) as lease:
        await lease.set_affinity(SecretStr("synthetic-affinity-only"))
        await lease.begin_turn("invocation-a", DIGEST)
        await lease.append_event(answer)
        await lease.append_event(answer)  # Idempotent journal append.
        await lease.complete_turn()
        with pytest.raises(CustomerChannelError, match="^display_recovery_required$"):
            await lease.begin_turn("invocation-b", DIGEST)
    await stores[0]._engine.dispose()
    async with await claim(stores[1]) as recovered:
        assert recovered.pending_invocation_id == "invocation-a"
        assert recovered.affinity.get_secret_value() == "synthetic-affinity-only"
        assert "synthetic-affinity" not in repr(recovered)
        saved = await recovered.read_completed("invocation-a")
        assert len(saved) == 1 and saved[0].model_dump() == answer.model_dump()
        saved[0].content.parts[0].text = "mutated"
        assert (await recovered.read_completed("invocation-a"))[
            0
        ].model_dump() == answer.model_dump()
        await recovered.acknowledge_display()
        assert recovered.pending_invocation_id is None
        with pytest.raises(CustomerChannelError, match="^duplicate_turn$"):
            await recovered.begin_turn("invocation-a", DIGEST)
        await recovered.begin_turn("invocation-b", DIGEST)
        another = final("next").model_copy(update={"invocation_id": "invocation-b"})
        await recovered.append_event(another)
        await recovered.complete_turn()
        await recovered.acknowledge_display()
        assert (await recovered.read_completed("invocation-a"))[
            0
        ].model_dump() == answer.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_expiry_never_takes_over_or_reenables_execution(stores, complete):
    now = [1000.0]
    for store in stores:
        store._clock = lambda: now[0]
    lease = await claim(stores[0], lease_seconds=5)
    await lease.begin_turn("invocation-a", DIGEST)
    if complete:
        await lease.append_event(final())
        await lease.complete_turn()
    now[0] += 6
    with pytest.raises(CustomerChannelError, match="^lease_expired$"):
        await lease.set_affinity(None)
    with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
        await claim(stores[1])
    await lease.close()
    await lease.close()
    if complete:
        async with await claim(stores[1]) as recovered:
            assert len(await recovered.read_completed("invocation-a")) == 1
    else:
        with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
            await claim(stores[1])


@pytest.mark.asyncio
async def test_cancelled_owner_blocks_replay(stores):
    started = asyncio.Event()

    async def work():
        async with await claim(stores[0]) as lease:
            await lease.begin_turn("invocation-a", DIGEST)
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(work())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
        await claim(stores[1])


@pytest.mark.asyncio
async def test_completed_required_before_ack_and_read(stores):
    async with await claim(stores[0]) as lease:
        await lease.begin_turn("invocation-a", DIGEST)
        for operation in (
            lease.complete_turn,
            lease.acknowledge_display,
            lambda: lease.read_completed("invocation-a"),
        ):
            with pytest.raises(CustomerChannelError):
                await operation()


@pytest.mark.asyncio
async def test_journal_rejects_partial_conflicts_wrong_identity_and_after_final(stores):
    async with await claim(stores[0]) as lease:
        await lease.begin_turn("invocation-a", DIGEST)
        with pytest.raises(CustomerChannelError, match="^invalid_journal_event$"):
            await lease.append_event(final(partial=True))
        with pytest.raises(CustomerChannelError, match="^invalid_journal_event$"):
            await lease.append_event(
                final().model_copy(update={"invocation_id": "other"})
            )
        answer = final()
        await lease.append_event(answer)
        changed = answer.model_copy(deep=True)
        changed.content.parts[0].text = "changed"
        with pytest.raises(CustomerChannelError, match="^event_conflict$"):
            await lease.append_event(changed)
        with pytest.raises(CustomerChannelError, match="^event_after_final$"):
            await lease.append_event(final("second"))


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["max_event_bytes", "max_turn_bytes", "max_events"])
async def test_journal_bounds(stores, limit):
    bounded = CustomerSessionStore(stores[0]._engine, **{limit: 1})
    async with await claim(bounded) as lease:
        await lease.begin_turn("invocation-a", DIGEST)
        if limit == "max_events":
            event = Event(
                author="local_agent",
                invocation_id="invocation-a",
                content=types.ModelContent(
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(name="lookup", id="a")
                        )
                    ]
                ),
            )
            await lease.append_event(event)
        with pytest.raises(CustomerChannelError, match="^journal_limit$"):
            await lease.append_event(final())


@pytest.mark.asyncio
async def test_closed_lease_cannot_write_to_next_owner(stores):
    first = await claim(stores[0])
    await first.close()
    async with await claim(stores[1]):
        with pytest.raises(CustomerChannelError, match="^lease_closed$"):
            await first.begin_turn("invocation-a", DIGEST)


@pytest.mark.asyncio
async def test_no_implicit_schema_and_sanitized_database_failure(tmp_path):
    engine = create_async_engine(
        "sqlite+aiosqlite:///" + str(tmp_path / "empty.db"), hide_parameters=True
    )
    try:
        with pytest.raises(CustomerChannelError, match="^store_unavailable$") as error:
            await claim(CustomerSessionStore(engine))
        assert error.value.__suppress_context__
    finally:
        await engine.dispose()


@pytest.mark.parametrize("setting", [{"echo": True}, {"hide_parameters": False}])
def test_rejects_engine_that_can_log_private_parameters(setting):
    options = {"hide_parameters": True, **setting}
    engine = create_async_engine("sqlite+aiosqlite://", **options)
    with pytest.raises(ValueError, match="safe database logging"):
        CustomerSessionStore(engine)


@pytest.mark.asyncio
async def test_waiting_for_writer_counts_against_operation_timeout(stores):
    async with await claim(stores[0]) as lease:
        stores[0]._timeout = 0.03
        async with lease._lock:
            with pytest.raises(CustomerChannelError, match="^store_unavailable$"):
                await asyncio.wait_for(lease.set_affinity(None), 1)


@pytest.mark.asyncio
async def test_parallel_close_is_idempotent(stores):
    lease = await claim(stores[0])
    await asyncio.gather(lease.close(), lease.close())
    async with await claim(stores[1]):
        pass


@pytest.mark.asyncio
async def test_expiry_during_reservation_rolls_back_every_write(stores, monkeypatch):
    now = [1000.0]
    stores[0]._clock = lambda: now[0]
    lease = await claim(stores[0], lease_seconds=5)
    original = lease._session_update

    async def expire(connection, **values):
        await original(connection, **values)
        now[0] += 6

    monkeypatch.setattr(lease, "_session_update", expire)
    with pytest.raises(CustomerChannelError, match="^lease_expired$"):
        await lease.begin_turn("invocation-a", DIGEST)
    monkeypatch.setattr(lease, "_session_update", original)
    await lease.close()
    async with await claim(stores[1]) as next_owner:
        # No reservation committed, so the caller could not have sent this run.
        await next_owner.begin_turn("invocation-a", DIGEST)


@pytest.mark.asyncio
async def test_non_json_state_rejected_before_serializer_or_logging(stores):
    class SensitiveObject:
        def __repr__(self):
            raise AssertionError("state repr must never be called")

    async with await claim(stores[0]) as lease:
        await lease.begin_turn("invocation-a", DIGEST)
        event = final()
        event.actions.state_delta = {"private": SensitiveObject()}
        with pytest.raises(CustomerChannelError, match="^invalid_journal_event$"):
            await lease.append_event(event)


@pytest.mark.asyncio
async def test_logging_reconfigured_after_construction_blocks_io(stores, monkeypatch):
    monkeypatch.setattr(stores[0]._engine.sync_engine, "hide_parameters", False)
    with pytest.raises(CustomerChannelError, match="^unsafe_database_logging$"):
        await claim(stores[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_seconds", 0),
        ("lease_seconds", float("inf")),
        ("lease_seconds", True),
        ("engine_id", ""),
        ("remote_app", "unmanaged"),
    ],
)
async def test_invalid_claim_inputs(stores, field, value):
    values = dict(
        engine_id="customer-v1", remote_app="managed_example", lease_seconds=180
    )
    values[field] = value
    with pytest.raises(ValueError, match="^Invalid customer session binding$"):
        await stores[0].claim(IDENTITY, **values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", ["", "raw-string", SecretStr(""), SecretStr("bad\nheader")]
)
async def test_affinity_requires_private_valid_value(stores, value):
    async with await claim(stores[0]) as lease:
        with pytest.raises(ValueError, match="^Invalid private affinity$"):
            await lease.set_affinity(value)


@pytest.mark.asyncio
async def test_journal_preserves_order_without_rewriting_previous_events(stores):
    from sqlalchemy import event as sql_event

    statements = []

    def observe(_conn, _cursor, statement, _params, _context, _many):
        # SQL shape only, never parameters or row contents.
        statements.append(statement.lower())

    sql_event.listen(stores[0]._engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with await claim(stores[0]) as lease:
            await lease.begin_turn("invocation-a", DIGEST)
            events = [
                Event(
                    author="local_agent",
                    invocation_id="invocation-a",
                    content=types.ModelContent(
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name="lookup", id=f"call-{i}", args={"index": i}
                                )
                            )
                        ]
                    ),
                )
                for i in range(20)
            ]
            for item in events:
                await lease.append_event(item)
            await lease.append_event(final())
            await lease.complete_turn()
            result = await lease.read_completed("invocation-a")
            assert [e.id for e in result[:-1]] == [e.id for e in events]
            assert not any(
                s.startswith("update veadk_customer_events_v1") for s in statements
            )
    finally:
        sql_event.remove(
            stores[0]._engine.sync_engine, "before_cursor_execute", observe
        )


@pytest.mark.asyncio
async def test_customer_tool_roundtrip_survives_local_display_save_failure(stores):
    import httpx
    from veadk.runtime.customer import CustomerAdkEventStream, CustomerToolDispatcher
    from tests.runtime.customer.test_channel import call, complete, request, tool
    from tests.runtime.customer.test_dispatch import Host
    from tests.runtime.customer.test_events import (
        MESSAGE,
        display_call,
        display_response,
        native,
        wire,
    )

    executions = []
    async with await claim(stores[0]) as lease:
        turn = await lease.begin_turn("invocation-a", DIGEST)
        run = request(tools=(tool(),)).model_copy(
            update={
                "app_name": lease.binding.remote_app,
                "user_id": lease.binding.remote_user,
                "session_id": lease.binding.remote_session,
                "new_message": MESSAGE,
                "run_id": turn.run_id,
                "channel_id": turn.channel_id,
                "scope_id": turn.scope_id,
            }
        )
        host = Host(run, [wire(run, display_call()), call(run)])

        async def executor(args, request_id):
            executions.append(request_id)
            return {"pages": [1, 2]}

        async def ack(_):
            host.send(wire(run, display_response()))
            host.send(wire(run, native(text="complete")))
            host.send(complete(run))
            return httpx.Response(200, json={"accepted": True})

        host.result_handler = ack
        async with host.client() as client:
            dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
            async with CustomerAdkEventStream(
                dispatch,
                author="local_agent",
                invocation_id="invocation-a",
                new_message=MESSAGE,
            ) as stream:
                async for item in stream.events():
                    if not item.partial:
                        await lease.append_event(item)
            assert dispatch.quiescent
            await lease.complete_turn()
        # A local Session save now fails: never acknowledge display or resubmit.
    request_count = len(host.requests)
    async with await claim(stores[1]) as recovered:
        events = await recovered.read_completed("invocation-a")
        assert events[0].get_function_calls()
        assert events[1].get_function_responses()
        assert events[-1].is_final_response()
        assert events[-1].content.parts[0].text == "complete"
        assert executions == ["call-a"] and len(host.results) == 1
        assert len(host.requests) == request_count and host.stream.closed
        with pytest.raises(CustomerChannelError, match="^duplicate_turn$"):
            await recovered.begin_turn("invocation-a", DIGEST)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"error_code": "synthetic_error"},
        {"interrupted": True},
        {"turn_complete": False},
        {"content": None},
    ],
)
async def test_failure_and_non_final_events_cannot_complete(stores, changes):
    async with await claim(stores[0]) as lease:
        await lease.begin_turn("invocation-a", DIGEST)
        await lease.append_event(final().model_copy(update=changes))
        with pytest.raises(CustomerChannelError, match="^missing_final_response$"):
            await lease.complete_turn()


@pytest.mark.asyncio
async def test_corrupt_journal_never_returns_raw_validation_error(stores):
    from sqlalchemy import update
    from veadk.runtime.customer.session_store import _journal

    async with await claim(stores[0]) as lease:
        await lease.begin_turn("invocation-a", DIGEST)
        await lease.append_event(final())
        await lease.complete_turn()
        async with stores[0]._engine.begin() as connection:
            await connection.execute(
                update(_journal).values(payload='{"synthetic":"broken"}')
            )
        with pytest.raises(CustomerChannelError, match="^journal_corrupt$"):
            await lease.read_completed("invocation-a")


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [False, True])
async def test_repeated_cancel_releases_lease_without_replaying(stores, running):
    lease = await claim(stores[0])
    started, cleaning, release = (asyncio.Event() for _ in range(3))
    update = lease._session_update

    async def paused_update(connection, **values):
        if "owner" in values:
            cleaning.set()
            await release.wait()
        return await update(connection, **values)

    lease._session_update = paused_update

    async def run_owned():
        async with lease:
            if running:
                await lease.begin_turn("invocation-a", DIGEST)
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run_owned())
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert lease._closed
        if running:
            with pytest.raises(CustomerChannelError, match="session_recovery_required"):
                await claim(stores[1])
        else:
            async with await claim(stores[1]):
                pass
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await lease.close()
