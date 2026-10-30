"""Executor deadline, independent stop proof, real Runner and durable reuse."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from veadk import Agent
from veadk.runtime.customer import CustomerChannelError
from tests.runtime.customer.test_channel import tool
from tests.runtime.customer.test_native_channel import CONFIG, NativeHost
from tests.runtime.customer.test_runtime import IDENTITY, turn
from tests.runtime.customer.test_runtime import setup as _shared_setup

setup = _shared_setup


async def exercise(setup, *, native, proof=True, callback=True):
    config, shared_host, sessions = setup
    stopped = asyncio.Event()
    executions, confirmations = [], []
    host = NativeHost((1,)) if native else shared_host

    async def handle(request):
        response = await host.handle(request)
        if not native and request.url.path.endswith("/http-runs") and host.use_tool:
            queue = host.hosts[-1].stream.queue
            envelopes = []
            while not queue.empty():
                envelope = queue.get_nowait()
                if envelope.get("type") == "tool.call":
                    envelope["deadline_ms"] = 30
                raw = envelope.get("event", {})
                if any(
                    p.get("functionResponse") or p.get("function_response")
                    for p in raw.get("content", {}).get("parts", [])
                ):
                    continue
                envelopes.append(envelope)
            for envelope in envelopes:
                queue.put_nowait(envelope)
        return response

    async def execute(args, request_id):
        executions.append(request_id)
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def confirm(context):
        assert stopped.is_set()
        streams = host.streams if native else [h.stream for h in host.hosts]
        assert streams and all(stream.closed for stream in streams)
        assert context.reason == "tool_timeout"
        confirmations.append(context)
        if proof == "throw":
            raise RuntimeError("synthetic confirmation failure")
        return proof

    config = replace(
        config,
        protocol="native" if native else "shared",
        agent_config=CONFIG if native else config.agent_config,
        tools=(tool(timeout_ms=30),),
        executors={"lookup": execute},
        transport=httpx.MockTransport(handle),
        confirm_cancellation=confirm if callback else None,
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    if not native:
        host.use_tool = host.wait = True
    if callback and proof is True:
        events = await turn(
            agent, sessions, "timed out input", invocation_id="timed-out"
        )
        assert events[-1].turn_complete and events[-1].interrupted
        assert not events[-1].partial
        assert events[-1].error_code == "tool_timeout"
        assert "timed out" in events[-1].content.parts[0].text
        saved = await sessions.get_session(**IDENTITY)
        terminals = [e for e in saved.events if e.error_code == "tool_timeout"]
        assert len(terminals) == 1 and terminals[0].id == events[-1].id
        assert len({e.id for e in saved.events}) == len(saved.events)
        snapshot = [e.model_dump(mode="json") for e in saved.events]
        context = confirmations[0]
        assert await config.store.cancellation_settled(
            tuple(IDENTITY.values()),
            context.invocation_id,
            context.turn,
            engine_id=config._binding_id,
        )
        if not native:
            host.use_tool = host.wait = False
        else:
            host.batches = []
        await turn(agent, sessions, "followup", invocation_id="followup")
        saved = await sessions.get_session(**IDENTITY)
        assert [
            e.model_dump(mode="json") for e in saved.events[: len(snapshot)]
        ] == snapshot
        assert [
            e.content.parts[0].text for e in saved.events if e.author == "user"
        ] == ["timed out input", "followup"]
        runs = (
            [json.loads(r.content) for r in host.requests if r.url.path == "/run_sse"]
            if native
            else host.runs
        )
        bindings = (
            [(r["appName"], r["userId"], r["sessionId"]) for r in runs]
            if native
            else [(r.app_name, r.user_id, r.session_id) for r in runs]
        )
        assert (
            bindings
            == [
                (
                    context.binding.remote_app,
                    context.binding.remote_user,
                    context.binding.remote_session,
                )
            ]
            * 2
        )
    else:
        with pytest.raises(CustomerChannelError, match="^tool_timeout$"):
            await turn(agent, sessions, "timed out input", invocation_id="timed-out")
        before = len(host.requests)
        with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
            await turn(agent, sessions, "followup")
        assert len(host.requests) == before
        saved = await sessions.get_session(**IDENTITY)
        assert not any(e.interrupted for e in saved.events)
    assert stopped.is_set() and len(executions) == 1
    assert len(confirmations) == (1 if callback else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_confirmed_tool_timeout_publishes_once_and_same_session_follows_up(
    setup, native
):
    await exercise(setup, native=native)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    "proof,callback", [(False, True), (1, True), ("throw", True), (True, False)]
)
async def test_unconfirmed_tool_timeout_keeps_quarantine(
    setup, native, proof, callback
):
    await exercise(setup, native=native, proof=proof, callback=callback)


@pytest.mark.asyncio
async def test_timeout_terminal_save_failure_recovers_display_without_host_or_executor_replay(
    setup, monkeypatch
):
    from veadk.runtime.customer import CustomerRuntime

    config, _, sessions = setup
    append = sessions.append_event
    rejected = []

    async def reject_terminal(*, session, event):
        if event.error_code == "tool_timeout":
            rejected.append(event.id)
            raise RuntimeError("synthetic display save failure")
        return await append(session=session, event=event)

    monkeypatch.setattr(sessions, "append_event", reject_terminal)
    host = NativeHost((1,))
    executions = []

    async def execute(args, request_id):
        executions.append(request_id)
        await asyncio.Event().wait()

    async def confirm(context):
        assert all(s.closed for s in host.streams)
        return True

    config = replace(
        config,
        protocol="native",
        agent_config=CONFIG,
        tools=(tool(timeout_ms=30),),
        executors={"lookup": execute},
        transport=httpx.MockTransport(host.handle),
        confirm_cancellation=confirm,
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(RuntimeError, match="synthetic display save failure"):
        await turn(agent, sessions, "timed out input", invocation_id="save-failed")
    before = len(host.requests)
    monkeypatch.setattr(sessions, "append_event", append)
    assert (
        await CustomerRuntime().recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
        == 1
    )
    assert len(host.requests) == before and len(executions) == 1
    saved = await sessions.get_session(**IDENTITY)
    terminals = [e for e in saved.events if e.error_code == "tool_timeout"]
    assert len(terminals) == 1 and terminals[0].id == rejected[0]
