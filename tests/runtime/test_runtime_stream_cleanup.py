"""Exercise delegated generator ownership through the production Agent boundary."""

import asyncio
import importlib
from contextlib import aclosing
from contextvars import ContextVar

import httpx
import pytest
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.session import Session
from google.genai import types

from veadk import Agent
from veadk.memory.short_term_memory import ShortTermMemory
from veadk.processors import BaseRunProcessor
from veadk.runner import Runner as VeRunner
from veadk.runtime import BaseRuntime
from veadk.runtime.customer import CustomerAdkEventStream, CustomerToolDispatcher
from tests.cloud.test_harness_app_call_limit import _serve
from tests.runtime.customer.test_channel import call, complete, ready, request, tool
from tests.runtime.customer.test_dispatch import Host, Stream
from tests.runtime.customer.test_events import (
    MESSAGE,
    display_call,
    display_response,
    native,
    wire,
)


class StreamRuntime(BaseRuntime):
    def __init__(self, *, failure=None):
        self.failure = failure
        self.entered = []
        self.closed = []
        self.generators = []
        self.context = ContextVar("synthetic_runtime_owner", default=None)
        self.wait_after_partial = False
        self.closed_signal = asyncio.Event()

    def run_async(self, agent, ctx):
        stream = self._events(agent, ctx)
        # Keep a reference so tests do not accidentally pass through GC cleanup.
        self.generators.append(stream)
        return stream

    async def _events(self, agent, ctx):
        owner = asyncio.current_task()
        self.entered.append(owner)
        token = self.context.set(owner)
        try:
            yield Event(
                author=agent.name,
                invocation_id=ctx.invocation_id,
                partial=True,
                content=types.ModelContent(parts=[types.Part(text="partial")]),
            )
            if self.wait_after_partial:
                await asyncio.Event().wait()
            if self.failure == "runtime":
                raise RuntimeError("synthetic runtime failure")
            yield Event(
                author=agent.name,
                invocation_id=ctx.invocation_id,
                content=types.ModelContent(parts=[types.Part(text="answer")]),
            )
        finally:
            assert self.context.get() is owner
            self.context.reset(token)
            self.closed.append(asyncio.current_task())
            self.closed_signal.set()
            if self.failure == "cleanup":
                raise RuntimeError("synthetic cleanup failure")


def bind(monkeypatch, runtime, name="piagent"):
    module = importlib.import_module("veadk.runtime")
    monkeypatch.setattr(module, "get_runtime", lambda selected: runtime)
    return Agent(name="local_agent", runtime=name, output_key="answer")


def context(agent):
    return InvocationContext(
        agent=agent,
        invocation_id="synthetic-invocation",
        session_service=InMemorySessionService(),
        session=Session(id="session-a", app_name="app", user_id="user-a"),
        user_content=types.Content(**MESSAGE),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["codex", "piagent", "dsh"])
@pytest.mark.parametrize("mode", ["complete", "close", "consumer_error", "cancel"])
async def test_runtime_closed_in_owner_task_before_consumer_returns(
    monkeypatch, name, mode
):
    runtime = StreamRuntime()
    agent = bind(monkeypatch, runtime, name)
    seen = []

    async def consume():
        try:
            async with aclosing(agent._run_async_impl(context(agent))) as events:
                async for event in events:
                    seen.append(event)
                    if mode == "close":
                        break
                    if mode == "consumer_error":
                        raise RuntimeError("synthetic consumer failure")
                    if mode == "cancel":
                        asyncio.current_task().cancel()
                        await asyncio.sleep(0)
        finally:
            try:
                assert runtime.closed == [asyncio.current_task()]
                assert runtime.context.get() is None
            finally:
                # Baseline failure still releases all test-owned generators.
                for stream in runtime.generators:
                    await stream.aclose()

    if mode == "consumer_error":
        with pytest.raises(RuntimeError, match="synthetic consumer failure"):
            await consume()
    elif mode == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(consume())
    else:
        await consume()
    assert runtime.entered == runtime.closed
    assert len(seen) == (2 if mode == "complete" else 1)
    assert seen[0].partial and not seen[0].actions.state_delta
    if mode == "complete":
        assert seen[1].actions.state_delta == {"answer": "answer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["runtime", "cleanup"])
async def test_runtime_and_cleanup_errors_are_not_silenced(monkeypatch, failure):
    runtime = StreamRuntime(failure=failure)
    agent = bind(monkeypatch, runtime)
    with pytest.raises(RuntimeError, match=f"synthetic {failure} failure"):
        async with aclosing(agent._run_async_impl(context(agent))) as events:
            async for _ in events:
                if failure == "cleanup":
                    break
    assert runtime.closed == runtime.entered


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["close", "consumer_error", "cancel"])
async def test_public_veadk_runner_closes_all_forwarding_layers(monkeypatch, mode):
    runtime = StreamRuntime()
    agent = bind(monkeypatch, runtime)
    service = InMemorySessionService()
    await service.create_session(
        app_name="app", user_id="user-a", session_id="session-a"
    )
    runner = VeRunner(
        app_name="app",
        agent=agent,
        short_term_memory=ShortTermMemory(session_service=service),
    )

    async def consume():
        try:
            async with aclosing(
                runner.run_async(
                    user_id="user-a",
                    session_id="session-a",
                    new_message=types.Content(**MESSAGE),
                )
            ) as events:
                async for _ in events:
                    if mode == "consumer_error":
                        raise RuntimeError("synthetic consumer failure")
                    if mode == "cancel":
                        asyncio.current_task().cancel()
                        await asyncio.sleep(0)
                    break
        finally:
            try:
                assert len(runtime.closed) == 1
                assert runtime.entered == runtime.closed
            finally:
                for owner in runtime.entered:
                    if not owner.done():
                        owner.cancel()
                        await asyncio.gather(owner, return_exceptions=True)

    if mode == "consumer_error":
        with pytest.raises(RuntimeError, match="synthetic consumer failure"):
            await consume()
    elif mode == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(consume())
    else:
        await consume()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_runner_run_processor_exit_closes_the_stream(monkeypatch, fail):
    class StopProcessor(BaseRunProcessor):
        def process_run(self, runner, message, **kwargs):
            def decorate(func):
                async def events():
                    async with aclosing(func()) as stream:
                        async for event in stream:
                            yield event
                            if fail:
                                raise RuntimeError("synthetic processor failure")
                            return

                return events

            return decorate

    runtime = StreamRuntime()
    agent = bind(monkeypatch, runtime)
    runner = VeRunner(
        app_name="app",
        agent=agent,
        run_processor=StopProcessor(),
        short_term_memory=ShortTermMemory(session_service=InMemorySessionService()),
    )
    try:
        if fail:
            with pytest.raises(RuntimeError, match="synthetic processor failure"):
                await runner.run(
                    messages="hello", user_id="user-a", session_id="session-a"
                )
        else:
            await runner.run(messages="hello", user_id="user-a", session_id="session-a")
        assert len(runtime.closed) == 1
        assert runtime.entered == runtime.closed
    finally:
        for owner in runtime.entered:
            if not owner.done():
                owner.cancel()
                await asyncio.gather(owner, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route,override", [("/run", False), ("/run_sse", False), ("/run_sse", True)]
)
@pytest.mark.parametrize("fail_save", [False, True])
async def test_standard_harness_http_finishes_cleanup_before_return(
    monkeypatch,
    route,
    override,
    fail_save,
):
    class Sessions(InMemorySessionService):
        async def append_event(self, session, event):
            if fail_save and event.author != "user" and not event.partial:
                raise RuntimeError("synthetic storage failure")
            return await super().append_event(session, event)

    runtime = StreamRuntime()
    agent = bind(monkeypatch, runtime)
    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    monkeypatch.setattr(module, "has_a2a_registry_config", lambda agent: False)
    app = module.HarnessApp(
        agent,
        ShortTermMemory(session_service=Sessions()),
        "app",
    ).app
    payload = {
        "app_name": "app",
        "user_id": "user-a",
        "session_id": "session-a",
        "streaming": True,
        "new_message": MESSAGE,
    }
    if override:
        payload["harness"] = {"system_prompt": "synthetic prompt"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        assert (
            await client.post("/apps/app/users/user-a/sessions/session-a", json={})
        ).status_code == 200
        for turn in range(2):
            response = await client.post(route, json=payload)
            assert len(runtime.closed) == turn + 1
            assert runtime.entered == runtime.closed
            if fail_save:
                if route == "/run":
                    assert response.status_code == 500
                else:
                    assert "synthetic storage failure" in response.text
            else:
                assert response.status_code == 200 and "answer" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [False, True])
async def test_loopback_http_disconnect_closes_runtime_and_can_send_again(
    monkeypatch,
    override,
):
    runtime = StreamRuntime()
    runtime.wait_after_partial = True
    agent = bind(monkeypatch, runtime)
    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    monkeypatch.setattr(module, "has_a2a_registry_config", lambda agent: False)
    app = module.HarnessApp(
        agent,
        ShortTermMemory(session_service=InMemorySessionService()),
        "app",
    ).app
    payload = {
        "app_name": "app",
        "user_id": "user-a",
        "session_id": "session-a",
        "streaming": True,
        "new_message": MESSAGE,
    }
    if override:
        payload["harness"] = {"system_prompt": "synthetic prompt"}
    async with _serve(app) as base:
        async with httpx.AsyncClient(base_url=base, timeout=5) as client:
            assert (
                await client.post("/apps/app/users/user-a/sessions/session-a", json={})
            ).status_code == 200
            async with client.stream("POST", "/run_sse", json=payload) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if "partial" in line:
                        break
            await asyncio.wait_for(runtime.closed_signal.wait(), 3)
            assert len(runtime.closed) == 1 and runtime.entered == runtime.closed
            runtime.wait_after_partial = False
            response = await client.post("/run_sse", json=payload)
            assert response.status_code == 200 and "answer" in response.text
            assert len(runtime.closed) == 2 and runtime.entered == runtime.closed


class FailingSessions(InMemorySessionService):
    async def append_event(self, session, event):
        if event.get_function_responses():
            raise RuntimeError("synthetic storage failure")
        return await super().append_event(session, event)


@pytest.mark.asyncio
async def test_real_agent_runner_save_failure_stops_customer_tools_and_allows_next_run(
    monkeypatch,
):
    run = request(tools=(tool(),)).model_copy(update={"new_message": MESSAGE})
    host = Host(
        run,
        [wire(run, display_call()), call(run), call(run, request_id="call-b")],
    )
    executions, dispatchers, closed = [], [], []
    active = set()
    second_started = asyncio.Event()

    async def executor(args, request_id):
        executions.append(request_id)
        active.add(request_id)
        try:
            if request_id == "call-b":
                second_started.set()
                await asyncio.Event().wait()
            await second_started.wait()
            return {"pages": [1, 2]}
        finally:
            active.remove(request_id)

    async def ack(_):
        host.send(wire(run, display_response()))
        return httpx.Response(200, json={"accepted": True})

    host.result_handler = ack
    async with host.client() as client:

        class CustomerFixtureRuntime(BaseRuntime):
            async def run_async(self, agent, ctx):
                dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
                dispatchers.append(dispatch)
                try:
                    async with CustomerAdkEventStream(
                        dispatch,
                        author=agent.name,
                        invocation_id=ctx.invocation_id,
                        new_message=MESSAGE,
                    ) as stream:
                        async for event in stream.events():
                            yield event
                finally:
                    closed.append(asyncio.current_task())

        agent = bind(monkeypatch, CustomerFixtureRuntime())
        service = FailingSessions()
        await service.create_session(
            app_name="app", user_id="user-a", session_id="session-a"
        )
        runner = Runner(app_name="app", agent=agent, session_service=service)

        async def invoke():
            emitted = []
            async with aclosing(
                runner.run_async(
                    user_id="user-a",
                    session_id="session-a",
                    new_message=types.Content(**MESSAGE),
                )
            ) as events:
                async for event in events:
                    emitted.append(event)
            return emitted

        with pytest.raises(RuntimeError, match="synthetic storage failure"):
            await asyncio.wait_for(invoke(), 2)
        assert len(closed) == 1
        assert dispatchers[0].quiescent and host.stream.closed
        assert not active and host.cancelled == 1
        assert executions == ["call-a", "call-b"] and len(host.results) == 1
        run = request(tools=(tool(),)).model_copy(update={"new_message": MESSAGE})
        host.stream = Stream([ready(), wire(run, native(text="next")), complete(run)])
        result = await asyncio.wait_for(invoke(), 2)
        assert result[-1].content.parts[0].text == "next"
        assert executions == ["call-a", "call-b"] and len(host.results) == 1
        assert len(closed) == 2 and all(item.quiescent for item in dispatchers)
        saved = await service.get_session(
            app_name="app", user_id="user-a", session_id="session-a"
        )
        assert len([e for e in saved.events if e.author == "user"]) == 2
        assert saved.state["answer"] == "next"
