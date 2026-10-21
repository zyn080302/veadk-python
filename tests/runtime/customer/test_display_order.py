"""Database readback must preserve publication order across async producers."""

import asyncio
import importlib
from contextlib import aclosing
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from tests.runtime.customer.test_channel import tool
from tests.runtime.customer.test_events import display_call, display_response, wire
from tests.runtime.customer.test_native_tools import NativeHost, agent_for
from tests.runtime.customer.test_runtime import IDENTITY, setup as runtime_setup, turn
from veadk import Agent
from veadk.runtime import get_runtime
from veadk.runtime.customer import CustomerChannelError
from veadk.runtime.customer.runtime import _event_payload

setup = runtime_setup


@pytest.mark.asyncio
@pytest.mark.parametrize("clock", ["normal", "frozen", "backward"])
async def test_interleaved_native_tool_readback_and_next_turn(
    setup, tmp_path, monkeypatch, clock
):
    config, _, _ = setup
    if clock != "normal":
        readings = iter(1_600_000_000 - i for i in range(100))
        module = importlib.import_module("veadk.runtime.customer.runtime")
        # Patch only Runtime's wall-clock reference, not ADK or asyncio clocks.
        monkeypatch.setattr(
            module,
            "time",
            SimpleNamespace(
                time=lambda: next(readings) if clock == "backward" else 1_600_000_000
            ),
        )
    db_url = "sqlite+aiosqlite:///" + str(tmp_path / "display.db")
    sessions = DatabaseSessionService(db_url=db_url)
    host = NativeHost()
    displayed = asyncio.Event()
    calls = []

    async def lookup(name: str) -> dict:
        calls.append(name)
        # The native call Event already exists, but its batch is not published
        # until this tool finishes. Host-only display may arrive in between.
        run, stream = host.runs[-1], host.hosts[-1]
        stream.send(wire(run, display_call(call_id="host-only", name="host_lookup")))
        response = display_response(call_id="host-only")
        response["content"]["parts"][0]["functionResponse"]["name"] = "host_lookup"
        stream.send(wire(run, response))
        await asyncio.wait_for(displayed.wait(), 2)
        return {"pages": [1, 2]}

    agent = agent_for(config, lookup, host)
    try:
        await sessions.create_session(**IDENTITY)
        runner = Runner(agent=agent, app_name="app", session_service=sessions)
        published = []
        async with aclosing(
            runner.run_async(
                user_id=IDENTITY["user_id"],
                session_id=IDENTITY["session_id"],
                new_message=types.UserContent(parts=[types.Part(text="first")]),
            )
        ) as events:
            async for event in events:
                published.append(event)
                if any(r.name == "host_lookup" for r in event.get_function_responses()):
                    displayed.set()

        assert len(calls) == 1
        expected = [e for e in published if not e.partial]
        # Exercise an actual database read, rather than the append-side Session.
        await sessions.close()
        sessions = DatabaseSessionService(db_url=db_url)
        saved = await sessions.get_session(**IDENTITY)
        ids = {e.id for e in expected}
        actual = [e for e in saved.events if e.id in ids]
        assert len(actual) == len(expected) == 5
        assert {e.id: _event_payload(e) for e in actual} == {
            e.id: _event_payload(e) for e in expected
        }
        assert [e.id for e in actual] == [e.id for e in expected]
        stored_times = [
            datetime.fromtimestamp(e.timestamp, timezone.utc) for e in actual
        ]
        assert all(a < b for a, b in zip(stored_times, stored_times[1:]))
        assert actual[-1].turn_complete
        await turn(agent.clone(), sessions, "second")
        assert len(host.runs) == len(calls) == 2
        assert all(len(h.results) == 1 for h in host.hosts)
    finally:
        await sessions.close()


@pytest.mark.asyncio
async def test_database_suffix_recovery_retains_journal_without_tool_replay(
    setup, tmp_path
):
    config, host, _ = setup
    host.use_tool = True
    config = replace(config, tools=(tool(),), executors={"lookup": host.lookup})
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    missing = []

    class FailingSessions(DatabaseSessionService):
        async def append_event(self, session, event):
            if event.turn_complete:
                missing.append(event.model_copy(deep=True))
                raise RuntimeError("synthetic display write failure")
            return await super().append_event(session, event)

    db_url = "sqlite+aiosqlite:///" + str(tmp_path / "recovery.db")
    sessions = FailingSessions(db_url=db_url)
    try:
        await sessions.create_session(**IDENTITY)
        with pytest.raises(RuntimeError, match="synthetic display write failure"):
            await turn(agent, sessions)
        before = await sessions.get_session(**IDENTITY)
        assert not any(e.turn_complete for e in before.events)
        assert len(missing) == len(host.executions) == len(host.runs) == 1
        requests = len(host.requests)
        await sessions.close()
        await config.store._engine.dispose()
        sessions = DatabaseSessionService(db_url=db_url)
        runtime = get_runtime("customer")
        assert (
            await runtime.recover_display(agent, sessions, tuple(IDENTITY.values()))
            == 1
        )
        assert (
            await runtime.recover_display(agent, sessions, tuple(IDENTITY.values()))
            == 0
        )
        saved = await sessions.get_session(**IDENTITY)
        assert [_event_payload(e) for e in saved.events] == [
            *(_event_payload(e) for e in before.events),
            _event_payload(missing[0]),
        ]
        assert len(host.requests) == requests
        assert len(host.executions) == 1
        await turn(agent.clone(), sessions, "second")
        assert len(host.executions) == len(host.runs) == 2
    finally:
        await sessions.close()


@pytest.mark.parametrize("change", ["content", "gap", "reordered", "duplicate"])
def test_publication_order_fix_preserves_strict_prefix_validation(change):
    from google.adk.events import Event
    from veadk.runtime.customer.runtime import _saved_prefix

    journal = [
        Event(
            author="customer_agent",
            timestamp=1_600_000_000 + index,
            content=types.ModelContent(parts=[types.Part(text=f"part {index}")]),
        )
        for index in range(3)
    ]
    saved = [e.model_copy(deep=True) for e in journal]
    if change == "content":
        saved[0].content.parts[0].text = "different"
    elif change == "gap":
        del saved[1]
    elif change == "reordered":
        saved.reverse()
    else:
        saved.append(saved[0].model_copy(deep=True))
    with pytest.raises(CustomerChannelError, match="^display_conflict$"):
        _saved_prefix(journal, SimpleNamespace(events=saved))
