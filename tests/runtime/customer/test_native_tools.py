"""Native tools through registered Runtime; all identities/data are synthetic."""

import asyncio
from contextvars import ContextVar
from dataclasses import replace

import httpx
import pytest
from google.adk.tools import ToolContext
from google.adk.sessions import InMemorySessionService

from veadk import Agent
from veadk.runtime import get_runtime
from veadk.runtime.customer import CustomerChannelError
from tests.runtime.customer.test_channel import call, complete, ready, tool
from tests.runtime.customer.test_events import (
    wire,
    native,
    display_call,
    display_response,
)
from tests.runtime.customer.test_runtime import (
    setup as runtime_setup,
    turn,
    IDENTITY,
    ManagedHost,
)


setup = runtime_setup


class NativeHost(ManagedHost):
    count = 1
    terminal = True

    async def handle(self, request):
        response = await super().handle(request)
        if request.url.path.endswith("/http-runs"):
            host, run = self.hosts[-1], self.runs[-1]
            while not host.stream.queue.empty():
                host.stream.queue.get_nowait()
            host.send(ready())
            for i in range(self.count):
                host.send(wire(run, display_call(call_id=f"remote-{i}")))
                host.send(call(run, request_id=f"control-{i}"))
                host.send(wire(run, display_response(call_id=f"remote-{i}")))

            async def acknowledge(message):
                if self.terminal and len(host.results) == self.count:
                    host.send(wire(run, native(text="answer")))
                    host.send(complete(run))
                return httpx.Response(200, json={"accepted": True})

            host.result_handler = acknowledge
        return response


def agent_for(config, lookup, host=None, **callbacks):
    if host is not None:
        config = replace(config, transport=httpx.MockTransport(host.handle))
    config = replace(config, native_tools=True, tools=(tool(),))
    return Agent(
        name="customer_agent",
        runtime="customer",
        customer_runtime_config=config,
        tools=[lookup],
        **callbacks,
    )


@pytest.mark.asyncio
async def test_native_callbacks_identity_serial_state_and_local_display(setup):
    config, _, sessions = setup
    host = NativeHost()
    host.count = 3
    identity = ContextVar("fixture_identity", default=None)
    identity.set("trusted-local-user")
    seen = []

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        seen.append(
            (
                identity.get(),
                tool_context._invocation_context.user_id,
                tool_context.state.get("counter", 0),
            )
        )
        await asyncio.sleep(0.001)
        tool_context.state["counter"] = tool_context.state.get("counter", 0) + 1
        tool_context.state["temp:counter"] = (
            tool_context.state.get("temp:counter", 0) + 1
        )
        return {"name": name, "counter": tool_context.state["counter"]}

    async def before(tool, args, tool_context):
        tool_context.state["before"] = True

    async def after(tool, args, tool_context, tool_response):
        assert tool_context.state["before"] is True
        return {**tool_response, "after": True}

    agent = agent_for(
        config, lookup, host, before_tool_callback=before, after_tool_callback=after
    )
    events = await turn(agent, sessions)
    assert seen == [("trusted-local-user", "user-a", i) for i in range(3)]
    responses = [r for e in events for r in e.get_function_responses()]
    calls = [c for e in events for c in e.get_function_calls()]
    assert len(calls) == len(responses) == 3
    assert {r.id for r in responses} == {c.id for c in calls}
    assert all(c.id not in {"remote-0", "control-0"} for c in calls)
    assert [r.response["counter"] for r in responses] == [1, 2, 3]
    assert all(r.response["after"] for r in responses)
    saved = await sessions.get_session(**IDENTITY)
    assert saved.state["counter"] == 3 and "temp:counter" not in saved.state
    assert all(
        not any(k.startswith("temp:") for k in e.actions.state_delta)
        for e in saved.events
    )
    assert len(host.hosts[0].results) == 3
    await turn(agent.clone(), sessions, "next")
    assert seen[-1][-1] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("recovered", [False, True])
async def test_native_tool_error_is_fixed_or_recovered_by_adk_callback(
    setup, recovered
):
    config, _, sessions = setup
    host = NativeHost()

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        tool_context.state["uncommitted"] = True
        raise RuntimeError("synthetic-private-error")

    async def on_error(tool, args, tool_context, error):
        assert isinstance(error, RuntimeError)
        tool_context.state["recovered"] = True
        return {"recovered": True}

    agent = agent_for(
        config,
        lookup,
        host,
        **({"on_tool_error_callback": on_error} if recovered else {}),
    )
    events = await turn(agent, sessions)
    responses = [r.response for e in events for r in e.get_function_responses()]
    assert responses == (
        [{"recovered": True}] if recovered else [{"error": "tool_execution_failed"}]
    )
    assert host.hosts[0].results[0]["status"] == ("success" if recovered else "error")
    saved = await sessions.get_session(**IDENTITY)
    assert ("uncommitted" in saved.state) == recovered
    assert "synthetic-private-error" not in str([e.model_dump() for e in events])


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["transfer", "skip", "shared_state", "non_json"])
async def test_unsupported_native_actions_fail_without_result_or_final(setup, action):
    config, _, sessions = setup
    host = NativeHost()

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        if action == "transfer":
            tool_context.actions.transfer_to_agent = "other"
        elif action == "skip":
            tool_context.actions.skip_summarization = True
        elif action == "shared_state":
            tool_context.state["user:counter"] = 1
        else:
            tool_context.state["invalid"] = object()
        return {"ok": True}

    with pytest.raises(CustomerChannelError, match="unsupported_native"):
        await turn(agent_for(config, lookup, host), sessions)
    assert not host.hosts[0].results
    saved = await sessions.get_session(**IDENTITY)
    assert not any(e.turn_complete for e in saved.events)
    assert not saved.state


@pytest.mark.asyncio
async def test_cancelled_native_tool_cannot_publish_late_state(setup):
    config, _, sessions = setup
    host = NativeHost()
    host.terminal = False
    started, late = asyncio.Event(), asyncio.Event()
    contexts = []

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        contexts.append(tool_context)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            tool_context.state["late"] = True
            late.set()
            return {"late": True}

    agent = agent_for(config, lookup, host)
    task = asyncio.create_task(turn(agent, sessions))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    await asyncio.wait_for(late.wait(), 1)
    contexts[0].state["later"] = True
    saved = await sessions.get_session(**IDENTITY)
    assert not saved.state and not host.hosts[0].results
    assert not any(e.get_function_responses() or e.turn_complete for e in saved.events)


@pytest.mark.asyncio
async def test_native_incomplete_journal_blocks_recovery_without_replay(setup):
    config, _, _ = setup
    host = NativeHost()
    calls = []

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        calls.append(name)
        tool_context.state["saved"] = True
        return {"ok": True}

    class Sessions(InMemorySessionService):
        fail = True

        async def append_event(self, session, event):
            if self.fail and event.get_function_responses():
                raise RuntimeError("fixture display save failure")
            return await super().append_event(session, event)

    sessions = Sessions()
    await sessions.create_session(**IDENTITY)
    agent = agent_for(config, lookup, host)
    with pytest.raises(RuntimeError, match="fixture display save failure"):
        await turn(agent, sessions)
    sessions.fail = False
    before = len(host.requests)
    # ADK may abort execution before final journaling. Never replay an uncertain
    # turn. This boundary is tested separately from completed final recovery.
    with pytest.raises(
        CustomerChannelError, match="session_recovery_required|turn_not_completed"
    ):
        await get_runtime("customer").recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
    assert len(host.requests) == before and len(calls) == 1


@pytest.mark.asyncio
async def test_native_catalog_mismatch_precedes_http(setup):
    config, _, sessions = setup
    host = NativeHost()

    async def lookup(unexpected: int) -> dict:
        return {}

    with pytest.raises((ValueError, CustomerChannelError), match="catalog|schema"):
        await turn(agent_for(config, lookup, host), sessions)
    assert not host.requests


@pytest.mark.asyncio
async def test_completed_native_actions_recover_from_deferred_adk_save(setup):
    config, _, _ = setup
    host = NativeHost()
    executed = []

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        executed.append(name)
        tool_context.state["recovered_state"] = 7
        return {"ok": True}

    class DeferredSessions(InMemorySessionService):
        defer = True

        async def append_event(self, session, event):
            if self.defer and event.get_function_responses():
                return event
            if self.defer and event.turn_complete:
                raise RuntimeError("fixture deferred save failed")
            return await super().append_event(session, event)

    sessions = DeferredSessions()
    await sessions.create_session(**IDENTITY)
    agent = agent_for(config, lookup, host)
    with pytest.raises(RuntimeError, match="fixture deferred save failed"):
        await turn(agent, sessions)
    assert not (await sessions.get_session(**IDENTITY)).state
    before = len(host.requests)
    sessions.defer = False
    assert (
        await get_runtime("customer").recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
        == 2
    )
    assert (await sessions.get_session(**IDENTITY)).state["recovered_state"] == 7
    assert len(host.requests) == before and len(executed) == 1
    assert (
        await get_runtime("customer").recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
        == 0
    )
    await turn(agent, sessions, "again")
    assert len(executed) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/run", "/run_sse"])
async def test_native_tools_real_loopback_harness_http(setup, monkeypatch, route):
    import importlib
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse, Response
    from tests.cloud.test_harness_app_call_limit import _serve
    from veadk.memory.short_term_memory import ShortTermMemory

    config, _, sessions = setup
    host = NativeHost()
    host_app = FastAPI()

    @host_app.api_route("/{path:path}", methods=["GET", "POST"])
    async def dispatch(request: Request, path: str):
        response = await host.handle(
            httpx.Request(
                request.method,
                "http://fixture/" + path,
                headers=request.headers,
                content=await request.body(),
            )
        )
        if response.headers.get("content-type") == "text/event-stream":

            async def stream():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()

            return StreamingResponse(stream(), headers=dict(response.headers))
        return Response(
            content=await response.aread(),
            status_code=response.status_code,
            headers=dict(response.headers),
        )

    identities = []

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        identities.append(tool_context._invocation_context.user_id)
        return {"name": name}

    async def after(tool, args, tool_context, tool_response):
        tool_context.state["calls"] = tool_context.state.get("calls", 0) + 1
        return {**tool_response, "calls": tool_context.state["calls"]}

    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    async with _serve(host_app) as endpoint:
        agent = agent_for(
            replace(config, endpoint=endpoint, transport=None),
            lookup,
            after_tool_callback=after,
        )
        app = module.HarnessApp(
            agent, ShortTermMemory(session_service=sessions), "app"
        ).app
        async with _serve(app) as base:
            async with httpx.AsyncClient(base_url=base, trust_env=False) as client:
                for text in ["first", "second"]:
                    response = await client.post(
                        route,
                        json={
                            **IDENTITY,
                            "new_message": {"role": "user", "parts": [{"text": text}]},
                            "streaming": True,
                        },
                    )
                    assert response.status_code == 200 and "answer" in response.text
                    assert '"error"' not in response.text
                response = await client.get("/apps/app/users/user-a/sessions/session-a")
                assert response.status_code == 200
                assert response.json()["state"]["calls"] == 2
    assert identities == ["user-a", "user-a"]
    assert len(host.runs) == 2 and all(
        len(h.results) == 1 and h.stream.closed for h in host.hosts
    )


@pytest.mark.asyncio
async def test_native_journal_failure_prevents_host_submission(setup, monkeypatch):
    from veadk.runtime.customer.session_store import CustomerSessionLease

    config, _, sessions = setup
    host = NativeHost()
    original = CustomerSessionLease.append_event

    async def fail_response(self, event):
        if event.get_function_responses():
            raise CustomerChannelError("fixture_journal_failed")
        await original(self, event)

    monkeypatch.setattr(CustomerSessionLease, "append_event", fail_response)

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        tool_context.state["must_not_commit"] = True
        return {"ok": True}

    with pytest.raises(CustomerChannelError, match="fixture_journal_failed"):
        await turn(agent_for(config, lookup, host), sessions)
    assert not host.hosts[0].results
    saved = await sessions.get_session(**IDENTITY)
    assert not saved.state and not any(e.turn_complete for e in saved.events)


@pytest.mark.asyncio
async def test_cancelled_control_call_has_no_native_state_or_result(setup):
    config, _, sessions = setup
    host = NativeHost()
    host.terminal = False
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def lookup(name: str, tool_context: ToolContext) -> dict:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            tool_context.state["late"] = True
            cancelled.set()
            return {"late": True}

    task = asyncio.create_task(turn(agent_for(config, lookup, host), sessions))
    await asyncio.wait_for(started.wait(), 2)
    host.hosts[0].send(
        {
            "type": "tool.cancel",
            "run_id": host.runs[0].run_id,
            "request_id": "control-0",
        }
    )
    await asyncio.wait_for(cancelled.wait(), 2)
    host.hosts[0].send(wire(host.runs[0], native(text="cancelled tool acknowledged")))
    host.hosts[0].send(complete(host.runs[0]))
    events = await asyncio.wait_for(task, 2)
    assert events[-1].turn_complete
    assert not any(e.get_function_responses() for e in events)
    assert not host.hosts[0].results
    assert not (await sessions.get_session(**IDENTITY)).state


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["sync", "long_running", "duplicate", "toolset"])
async def test_unsupported_native_catalogs_rejected_before_host(setup, kind):
    from google.adk.tools.function_tool import FunctionTool
    from google.adk.tools.base_toolset import BaseToolset

    config, _, sessions = setup
    host = NativeHost()

    async def lookup(name: str) -> dict:
        return {}

    entries = [lookup]
    if kind == "sync":

        def sync_lookup(name: str) -> dict:
            return {}

        entries = [FunctionTool(sync_lookup)]
    elif kind == "long_running":
        item = FunctionTool(lookup)
        item.is_long_running = True
        entries = [item]
    elif kind == "duplicate":
        entries = [lookup, lookup]
    else:

        class Toolset(BaseToolset):
            async def get_tools(self, readonly_context=None):
                pytest.fail("dynamic toolset must not be opened")

            async def close(self):
                pass

        entries = [Toolset()]
    agent = agent_for(config, lookup, host)
    agent.tools = entries
    with pytest.raises(
        CustomerChannelError, match="unsupported_native_tool|native_catalog_mismatch"
    ):
        await turn(agent, sessions)
    assert not host.requests


@pytest.mark.asyncio
async def test_native_media_result_is_rejected_instead_of_silently_dropped(setup):
    from google.genai import types

    config, _, sessions = setup
    host = NativeHost()

    async def lookup(name: str) -> dict:
        return {
            "asset": types.Part.from_bytes(
                data=b"synthetic-image", mime_type="image/png"
            )
        }

    with pytest.raises(CustomerChannelError, match="unsupported_native_response"):
        await turn(agent_for(config, lookup, host), sessions)
    assert not host.hosts[0].results
    assert not any(
        e.turn_complete for e in (await sessions.get_session(**IDENTITY)).events
    )


@pytest.mark.asyncio
async def test_host_only_tool_display_is_preserved_without_local_execution(setup):
    config, _, sessions = setup

    class SkillsHost(NativeHost):
        async def handle(self, request):
            response = await super().handle(request)
            if request.url.path.endswith("/http-runs"):
                host, run = self.hosts[-1], self.runs[-1]
                host.send(
                    wire(run, display_call(call_id="host-skill", name="read_skill"))
                )
                host.send(
                    wire(run, display_response(call_id="host-skill", name="read_skill"))
                )
            return response

    host = SkillsHost()
    executed = []

    async def lookup(name: str) -> dict:
        executed.append(name)
        return {"ok": True}

    events = await turn(agent_for(config, lookup, host), sessions)
    names = [c.name for e in events for c in e.get_function_calls()]
    assert sorted(names) == ["lookup", "read_skill"]
    assert len(executed) == len(host.hosts[0].results) == 1
