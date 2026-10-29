"""Real Runner channel failure, independently confirmed disconnect and reuse."""

from dataclasses import replace

import httpx
import pytest

from veadk import Agent
from veadk.runtime.customer import CustomerChannelError
from tests.runtime.customer.test_runtime import IDENTITY, turn
from tests.runtime.customer.test_runtime import setup as _shared_setup

setup = _shared_setup


async def exercise(setup, *, confirmed):
    config, host, sessions = setup
    confirmations = []
    broken = True
    original_handle = host.handle

    class BrokenStream(httpx.AsyncByteStream):
        def __init__(self, source):
            self.source = source

        async def __aiter__(self):
            async for chunk in self.source:
                yield chunk
                raise httpx.ReadError("synthetic stream disconnected")

        async def aclose(self):
            await self.source.aclose()

    async def handle(request):
        response = await original_handle(request)
        if broken and request.url.path.endswith("/http-runs"):
            response.stream = BrokenStream(response.stream)
        return response

    async def confirm(context):
        # Closing an HTTP reader alone is not remote stop proof. This fixture
        # independently supplies the exact-owner server confirmation result.
        assert host.hosts[0].stream.closed
        confirmations.append(context)
        return confirmed

    config = replace(
        config,
        transport=httpx.MockTransport(handle),
        confirm_cancellation=confirm,
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    host.wait = True
    with pytest.raises(CustomerChannelError, match="^transport_error$"):
        await turn(
            agent,
            sessions,
            "interrupted input",
            invocation_id="disconnected-invocation",
        )
    broken = host.wait = False
    if confirmed is True:
        await turn(agent, sessions, "followup", invocation_id="followup-invocation")
        assert len(confirmations) == 1
        context = confirmations[0]
        assert context.local_identity == tuple(IDENTITY.values())
        assert context.invocation_id == "disconnected-invocation"
        assert [(r.app_name, r.user_id, r.session_id) for r in host.runs] == [
            (
                context.binding.remote_app,
                context.binding.remote_user,
                context.binding.remote_session,
            )
        ] * 2
        saved = await sessions.get_session(**IDENTITY)
        assert [
            e.content.parts[0].text for e in saved.events if e.author == "user"
        ] == ["interrupted input", "followup"]
        interrupted = [e for e in saved.events if e.interrupted]
        assert len(interrupted) == 1 and interrupted[0].turn_complete
        assert interrupted[0].error_code == "customer_turn_cancelled"
        assert interrupted[0].invocation_id == "disconnected-invocation"
        assert host.executions == []
    else:
        with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
            await turn(agent, sessions, "followup")
        assert len(host.runs) == 1
        saved = await sessions.get_session(**IDENTITY)
        assert not any(e.interrupted for e in saved.events)


@pytest.mark.asyncio
async def test_confirmed_disconnection_transport_error_preserves_history_and_same_session(
    setup,
):
    await exercise(setup, confirmed=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, None, 1, "yes"])
async def test_unconfirmed_transport_error_retains_quarantine(setup, confirmed):
    await exercise(setup, confirmed=confirmed)


async def exercise_native(setup, *, code="transport_error", proof=True, callback=True):
    import json
    from tests.runtime.customer.test_native_channel import CONFIG, NativeHost

    config, _, sessions = setup
    host = NativeHost(())
    broken = True
    confirmations = []

    class BrokenStream(httpx.AsyncByteStream):
        def __init__(self, source):
            self.source = source

        async def __aiter__(self):
            async for chunk in self.source:
                yield chunk
                if code == "transport_error":
                    raise httpx.ReadError("synthetic native disconnect")
                raise CustomerChannelError(code)

        async def aclose(self):
            await self.source.aclose()

    async def handle(request):
        host.mutation = (
            (lambda events: events[0].update(partial=True)) if broken else None
        )
        response = await host.handle(request)
        if broken and request.url.path == "/run_sse":
            response.stream = BrokenStream(response.stream)
        return response

    async def confirm(context):
        assert host.streams[0].closed
        confirmations.append(context)
        if proof == "throw":
            raise RuntimeError("synthetic confirmation failure")
        return proof

    config = replace(
        config,
        protocol="native",
        agent_config=CONFIG,
        transport=httpx.MockTransport(handle),
        confirm_cancellation=confirm if callback else None,
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(CustomerChannelError, match="^" + code + "$"):
        await turn(
            agent,
            sessions,
            "interrupted native input",
            invocation_id="native-interrupted",
        )
    broken = False
    recoverable = callback and proof is True and code == "transport_error"
    if recoverable:
        events = await turn(
            agent, sessions, "native followup", invocation_id="native-next"
        )
        assert events[-1].turn_complete
        payloads = [
            json.loads(r.content) for r in host.requests if r.url.path == "/run_sse"
        ]
        assert len(payloads) == 2
        assert [(p["appName"], p["userId"], p["sessionId"]) for p in payloads] == [
            (
                confirmations[0].binding.remote_app,
                confirmations[0].binding.remote_user,
                confirmations[0].binding.remote_session,
            )
        ] * 2
        saved = await sessions.get_session(**IDENTITY)
        assert [
            e.content.parts[0].text for e in saved.events if e.author == "user"
        ] == ["interrupted native input", "native followup"]
        interrupted = [e for e in saved.events if e.interrupted]
        assert len(interrupted) == 1 and interrupted[0].turn_complete
        assert interrupted[0].invocation_id == "native-interrupted"
        assert interrupted[0].error_code == "customer_turn_cancelled"
        assert not host.executed
    else:
        before = len(host.requests)
        with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
            await turn(agent, sessions, "native followup")
        assert len(host.requests) == before
    assert len(confirmations) == (1 if callback and code == "transport_error" else 0)


@pytest.mark.asyncio
async def test_native_confirmed_transport_failure_allows_same_session_followup(setup):
    await exercise_native(setup)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proof,callback,code",
    [
        (False, True, "transport_error"),
        (None, True, "transport_error"),
        (1, True, "transport_error"),
        ("yes", True, "transport_error"),
        ("throw", True, "transport_error"),
        (True, False, "transport_error"),
        (True, True, "invalid_content_type"),
        (True, True, "run_timeout"),
    ],
)
async def test_native_unconfirmed_or_unrelated_failure_stays_blocked(
    setup, proof, callback, code
):
    await exercise_native(setup, proof=proof, callback=callback, code=code)
