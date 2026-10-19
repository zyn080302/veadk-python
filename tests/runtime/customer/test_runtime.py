"""Registered customer Runtime through actual Agent, Runner and Harness entrypoints."""

import asyncio
import importlib
import json
from contextlib import aclosing
from dataclasses import replace

import httpx
import pytest
import pytest_asyncio
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from veadk import Agent
from veadk.runtime import get_runtime
from veadk.runtime.customer import (
    CustomerChannelError,
    CustomerRuntime,
    CustomerRuntimeConfig,
    CustomerSessionStore,
)
from tests.runtime.customer.test_channel import call, complete, tool
from tests.runtime.customer.test_dispatch import Host
from tests.runtime.customer.test_events import (
    native,
    wire,
    display_call,
    display_response,
)

IDENTITY = dict(app_name="app", user_id="user-a", session_id="session-a")


class ManagedHost:
    def __init__(self):
        self.sessions = set()
        self.runs = []
        self.requests = []
        self.hosts = []
        self.executions = []
        self.failure = False
        self.wait = False
        self.use_tool = False

    async def lookup(self, args, request_id):
        self.executions.append((args, request_id))
        return {"pages": [1, 2]}

    async def handle(self, request):
        from veadk.runtime.customer import CustomerRunRequest

        self.requests.append(request)
        path = request.url.path
        if path.endswith("/http-runs"):
            data = json.loads(request.content)
            payload = data["payload"]
            remote_path = (
                "/managed/apps/{app_name}/users/{user_id}/sessions/{session_id}".format(
                    **payload
                )
            )
            if remote_path not in self.sessions:
                return httpx.Response(404, json={"error": "missing fixture session"})
            run = CustomerRunRequest(
                **{
                    k: data[k]
                    for k in ("run_id", "channel_id", "scope_id", "tools", "skills")
                },
                **{
                    k: payload[k]
                    for k in ("app_name", "user_id", "session_id", "new_message")
                },
                agent_config=SecretStr(data["agent_config"]),
            )
            self.runs.append(run)
            events = [wire(run, native(text="partial", partial=True))]
            if self.use_tool:
                events.extend(
                    [
                        wire(run, display_call()),
                        call(run),
                        wire(run, display_response()),
                    ]
                )
            if not self.wait:
                events.extend(
                    [
                        wire(run, native(text="answer")),
                        complete(run, "error" if self.failure else "success"),
                    ]
                )
            host = Host(run, events)
            self.hosts.append(host)
            response = await host.handle(request)
            response.headers["X-Session-Id"] = "synthetic-affinity"
            return response
        if path.endswith("/messages"):
            return await self.hosts[-1].handle(request)
        if request.method == "POST" and path.endswith("/sessions"):
            session_id = json.loads(request.content)["sessionId"]
            self.sessions.add(path + "/" + session_id)
            return httpx.Response(
                200,
                json={"id": session_id},
                headers={"X-Session-Id": "synthetic-affinity"},
            )
        if request.method == "GET" and "/sessions/" in path:
            return httpx.Response(
                200 if path in self.sessions else 404,
                json={"id": path.rsplit("/", 1)[-1]},
                headers={"X-Session-Id": "synthetic-affinity"},
            )
        raise AssertionError("unexpected local fixture route")


@pytest_asyncio.fixture
async def setup(tmp_path):
    engine = create_async_engine(
        "sqlite+aiosqlite:///" + str(tmp_path / "runtime.db"), hide_parameters=True
    )
    store = CustomerSessionStore(engine)
    await store.initialize()
    host = ManagedHost()
    config = CustomerRuntimeConfig(
        endpoint="https://host.invalid",
        engine_id="example-v1",
        remote_app="managed_example",
        agent_config=SecretStr("synthetic-config"),
        store=store,
        transport=httpx.MockTransport(host.handle),
    )
    sessions = InMemorySessionService()
    await sessions.create_session(**IDENTITY)
    try:
        yield config, host, sessions
    finally:
        await engine.dispose()


async def turn(agent, sessions, text="hello", invocation_id=None):
    runner = Runner(agent=agent, app_name="app", session_service=sessions)
    async with aclosing(
        runner.run_async(
            user_id="user-a",
            session_id="session-a",
            new_message=types.UserContent(parts=[types.Part(text=text)]),
            invocation_id=invocation_id,
        )
    ) as stream:
        return [event async for event in stream]


@pytest.mark.asyncio
async def test_registered_runtime_skips_model_setup_and_survives_clone(
    setup, monkeypatch
):
    config, host, sessions = setup
    module = importlib.import_module("veadk.agent")
    monkeypatch.delenv("MODEL_AGENT_API_KEY", raising=False)
    monkeypatch.setattr(
        module, "RetryingLiteLlm", lambda **_: pytest.fail("local model constructed")
    )
    monkeypatch.setattr(
        "veadk.auth.veauth.ark_veauth.get_ark_token",
        lambda **_: pytest.fail("local key lookup"),
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    assert isinstance(get_runtime("customer"), CustomerRuntime)
    assert agent.model_api_key == "" and not agent.model
    assert (
        "synthetic-config" not in repr(agent) + repr(config) + agent.model_dump_json()
    )
    assert "customer_runtime_config" not in agent.model_dump()
    cloned = agent.clone()
    assert cloned.customer_runtime_config is config
    result = await turn(cloned, sessions)
    assert result[-1].content.parts[0].text == "answer"
    await turn(agent.clone(), sessions, "follow-up")
    assert len(host.runs) == 2
    assert host.runs[0].session_id == host.runs[1].session_id
    assert host.runs[1].new_message == {
        "role": "user",
        "parts": [{"text": "follow-up"}],
    }
    assert all(
        request.headers.get("X-Session-Id") == "synthetic-affinity"
        for request in host.requests[2:]
    )


@pytest.mark.asyncio
async def test_durable_affinity_is_loaded_by_a_new_client(setup):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    await turn(agent, sessions)
    host.requests.clear()
    await config.store._engine.dispose()
    await turn(agent.clone(), sessions, "again")
    assert host.requests[0].headers["X-Session-Id"] == "synthetic-affinity"
    assert (
        sum(
            request.method == "POST" and request.url.path.endswith("/sessions")
            for request in host.requests
        )
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["endpoint", "agent_config", "engine_id", "remote_app"]
)
async def test_configuration_change_cannot_reuse_history(setup, change):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    await turn(agent, sessions)
    value = {
        "endpoint": "https://other.invalid",
        "agent_config": SecretStr("different-config"),
        "engine_id": "v2",
        "remote_app": "managed_other",
    }[change]
    changed = Agent(
        name="customer_agent",
        runtime="customer",
        customer_runtime_config=replace(config, **{change: value}),
    )
    with pytest.raises(CustomerChannelError, match="^engine_mismatch$"):
        await turn(changed, sessions)
    assert len(host.runs) == 1


@pytest.mark.asyncio
async def test_missing_remote_history_never_creates_an_empty_replacement(setup):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    await turn(agent, sessions)
    host.sessions.clear()
    requests_before = len(host.requests)
    with pytest.raises(CustomerChannelError, match="^http_status_404$"):
        await turn(agent, sessions)
    assert len(host.runs) == 1
    assert [r.method for r in host.requests[requests_before:]] == ["POST"]


@pytest.mark.asyncio
async def test_legacy_adk_history_cannot_silently_change_engine(setup):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    session = await sessions.get_session(**IDENTITY)
    await sessions.append_event(
        session,
        Event(
            author="previous_agent",
            content=types.ModelContent(parts=[types.Part(text="old answer")]),
        ),
    )
    with pytest.raises(
        CustomerChannelError, match="^legacy_session_requires_migration$"
    ):
        await turn(agent, sessions)
    assert not host.requests


@pytest.mark.asyncio
async def test_actual_adk_save_failure_recovers_display_without_tool_replay(setup):
    config, host, _ = setup
    host.use_tool = True
    config = replace(config, tools=(tool(),), executors={"lookup": host.lookup})
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )

    class Sessions(InMemorySessionService):
        fail = True

        async def append_event(self, session, event):
            if self.fail and event.author != "user" and event.turn_complete:
                raise RuntimeError("synthetic save failure")
            return await super().append_event(session, event)

    sessions = Sessions()
    await sessions.create_session(**IDENTITY)
    with pytest.raises(RuntimeError, match="synthetic save failure"):
        await turn(agent, sessions)
    assert len(host.executions) == len(host.runs) == 1
    requests_before = len(host.requests)
    sessions.fail = False
    await config.store._engine.dispose()
    count = await get_runtime("customer").recover_display(
        agent, sessions, tuple(IDENTITY.values())
    )
    assert count == 1
    assert len(host.requests) == requests_before
    assert (
        await get_runtime("customer").recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
        == 0
    )
    saved = await sessions.get_session(**IDENTITY)
    assert len([e for e in saved.events if e.turn_complete]) == 1
    await turn(agent, sessions, "next input")
    assert len(host.executions) == len(host.runs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("model_name", "other-model"),
        ("model_api_key", "synthetic-only"),
        ("model_extra_config", {"extra_headers": {"example": "synthetic"}}),
        ("instruction", "ignored prompt"),
        ("output_key", "answer"),
        ("before_model_callback", lambda: None),
        ("tools", [lambda: None]),
    ],
)
async def test_unsupported_agent_fields_fail_before_effects(setup, field, value):
    config, host, _ = setup
    with pytest.raises(ValueError, match="Unsupported customer Agent field"):
        Agent(
            name="customer_agent",
            runtime="customer",
            customer_runtime_config=config,
            **{field: value},
        )
    assert not host.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["clone", "assignment", "update_model"])
async def test_bound_agent_cannot_switch_to_local_model(setup, mutation):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(ValueError):
        if mutation == "update_model":
            agent.update_model("other")
        else:
            if mutation == "clone":
                agent = agent.clone(update={"runtime": "adk"})
            else:
                agent.runtime = "adk"
            await turn(agent, sessions)
    assert not host.requests


@pytest.mark.asyncio
async def test_error_and_cancellation_block_uncertain_replay(setup):
    config, host, sessions = setup
    host.wait = True
    config = replace(config, total_timeout=0.2, cleanup_timeout=0.2)
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(CustomerChannelError, match="timeout"):
        await turn(agent, sessions)
    assert host.hosts[0].stream.closed
    assert host.hosts[0].cancelled == 1
    with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
        await turn(agent, sessions)
    assert len(host.runs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/run", "/run_sse"])
@pytest.mark.parametrize("override", [None, {"runtime": "customer"}])
async def test_standard_harness_registered_customer_roundtrip(
    setup, monkeypatch, route, override
):
    from veadk.memory.short_term_memory import ShortTermMemory

    config, host, sessions = setup
    host.use_tool = True
    config = replace(config, tools=(tool(),), executors={"lookup": host.lookup})
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    app = module.HarnessApp(agent, ShortTermMemory(session_service=sessions), "app").app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        for text in ("first", "second"):
            payload = {
                **IDENTITY,
                "new_message": {"role": "user", "parts": [{"text": text}]},
                "streaming": True,
            }
            if override is not None:
                payload["harness"] = override
            response = await client.post(route, json=payload)
            assert response.status_code == 200 and "answer" in response.text, (
                response.text
            )
            assert "error" not in response.text.lower()
    assert len(host.runs) == len(host.executions) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"runtime": "adk"},
        {"model_name": "other"},
        {"system_prompt": "other"},
        {"temperature": 0.2},
        {"mcp": []},
    ],
)
async def test_harness_overrides_are_server_owned(setup, override):
    from veadk.cloud.harness_app.types import HarnessOverrides
    from veadk.cloud.harness_app.utils import spawn_harness_agent

    config, host, _ = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(ValueError, match="server-owned"):
        spawn_harness_agent(agent, HarnessOverrides(**override))
    assert not host.requests


@pytest.mark.asyncio
async def test_private_affinity_persisted_before_reuse_and_failure_is_redacted():
    from veadk.runtime.customer import CustomerChannelClient

    saved = []
    seen = []

    async def persist(value):
        await asyncio.sleep(0)
        saved.append(value.get_secret_value())

    async def handle(request):
        seen.append((request.headers.get("X-Session-Id"), list(saved)))
        return httpx.Response(
            200,
            json={"id": "remote-session"},
            headers={"X-Session-Id": "synthetic-new-affinity"},
        )

    async with CustomerChannelClient(
        "https://host.invalid",
        transport=httpx.MockTransport(handle),
        on_affinity=persist,
    ) as client:
        client.restore_session(
            "managed_example",
            "remote-user",
            "remote-session",
            affinity=SecretStr("synthetic-old-affinity"),
        )
        assert await client.session_exists(
            "managed_example", "remote-user", "remote-session"
        )
        assert await client.session_exists(
            "managed_example", "remote-user", "remote-session"
        )
        with pytest.raises(CustomerChannelError, match="session_mismatch"):
            await client.session_exists(
                "managed_example", "other-user", "remote-session"
            )
    assert seen == [
        ("synthetic-old-affinity", []),
        ("synthetic-new-affinity", ["synthetic-new-affinity"]),
    ]

    async def fail(_):
        raise RuntimeError("synthetic-private-body-must-not-escape")

    async with CustomerChannelClient(
        "https://host.invalid", transport=httpx.MockTransport(handle), on_affinity=fail
    ) as client:
        for _ in range(2):
            with pytest.raises(
                CustomerChannelError, match="^affinity_persistence_failed$"
            ):
                await client.session_exists(
                    "managed_example", "remote-user", "remote-session"
                )


@pytest.mark.asyncio
async def test_explicit_call_budget_rejected_instead_of_ignored(setup):
    from google.adk.agents.run_config import RunConfig

    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    runner = Runner(agent=agent, app_name="app", session_service=sessions)
    with pytest.raises(ValueError, match="Unsupported customer RunConfig"):
        async with aclosing(
            runner.run_async(
                user_id="user-a",
                session_id="session-a",
                new_message=types.UserContent(parts=[types.Part(text="query")]),
                run_config=RunConfig(max_llm_calls=2),
            )
        ) as events:
            _ = [event async for event in events]
    assert not host.requests


@pytest.mark.asyncio
async def test_cancelled_invocation_cleans_http_and_does_not_replay(setup):
    config, host, sessions = setup
    host.wait = True
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    pending = asyncio.create_task(turn(agent, sessions))
    for _ in range(200):
        if host.hosts:
            break
        await asyncio.sleep(0.005)
    assert host.hosts
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 2)
    assert host.hosts[0].stream.closed
    assert host.hosts[0].cancelled == 1
    with pytest.raises(CustomerChannelError, match="^session_recovery_required$"):
        await turn(agent, sessions)
    assert len(host.runs) == 1


@pytest.mark.asyncio
async def test_failure_terminal_has_no_success_answer(setup):
    config, host, sessions = setup
    host.failure = True
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(CustomerChannelError):
        await turn(agent, sessions)
    saved = await sessions.get_session(**IDENTITY)
    assert not any(
        event.turn_complete and not event.error_code for event in saved.events
    )
    assert len(host.runs) == 1


@pytest.mark.asyncio
async def test_real_loopback_harness_and_customer_http_with_tools(setup, monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse, Response
    from veadk.memory.short_term_memory import ShortTermMemory
    from tests.cloud.test_harness_app_call_limit import _serve

    config, host, sessions = setup
    host.use_tool = True
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

            return StreamingResponse(
                stream(),
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        return Response(
            content=await response.aread(),
            status_code=response.status_code,
            headers=dict(response.headers),
        )

    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    async with _serve(host_app) as endpoint:
        config = replace(
            config,
            endpoint=endpoint,
            transport=None,
            tools=(tool(),),
            executors={"lookup": host.lookup},
        )
        agent = Agent(
            name="customer_agent", runtime="customer", customer_runtime_config=config
        )
        app = module.HarnessApp(
            agent, ShortTermMemory(session_service=sessions), "app"
        ).app
        async with _serve(app) as base:
            async with httpx.AsyncClient(base_url=base, trust_env=False) as client:
                for text in ("first", "second"):
                    response = await client.post(
                        "/run_sse",
                        json={
                            **IDENTITY,
                            "new_message": {"role": "user", "parts": [{"text": text}]},
                            "streaming": True,
                        },
                    )
                    assert response.status_code == 200 and "answer" in response.text
                    assert '"error"' not in response.text
                history = (
                    await client.get("/apps/app/users/user-a/sessions/session-a")
                ).json()
                assert (
                    len(
                        [
                            e
                            for e in history["events"]
                            if e.get("turnComplete") or e.get("turn_complete")
                        ]
                    )
                    == 2
                )
    assert len(host.runs) == len(host.executions) == 2
    assert all(h.stream.closed for h in host.hosts)


@pytest.mark.asyncio
async def test_concurrent_runtime_invocations_have_one_owner(setup):
    config, host, sessions = setup
    host.wait = True
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    pending = asyncio.create_task(turn(agent, sessions))
    for _ in range(200):
        if host.hosts:
            break
        await asyncio.sleep(0.005)
    assert host.hosts
    try:
        with pytest.raises(CustomerChannelError, match="^session_busy$"):
            await turn(agent.clone(), sessions, "competing request")
        assert len(host.runs) == 1
    finally:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 2)
    assert host.hosts[0].stream.closed


@pytest.mark.asyncio
async def test_conflicting_persisted_display_blocks_without_http(setup):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    await turn(agent, sessions)
    session = await sessions.get_session(**IDENTITY)
    final = next(e for e in session.events if e.turn_complete)
    # InMemorySessionService returns copies; insert a duplicate ID to model a
    # storage conflict rather than mutating the Runtime's Event in memory.
    altered = final.model_copy(deep=True)
    altered.content.parts[0].text = "different saved text"
    await sessions.append_event(session, altered)
    before = len(host.requests)
    with pytest.raises(CustomerChannelError, match="^display_conflict$"):
        await get_runtime("customer").recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
    assert len(host.requests) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   "])
async def test_empty_input_never_reserves_or_calls_host(setup, text):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(CustomerChannelError, match="^unsupported_user_message$"):
        await turn(agent, sessions, text)
    assert not host.requests


@pytest.mark.asyncio
async def test_customer_harness_rejects_local_call_limit(setup, monkeypatch):
    from veadk.memory.short_term_memory import ShortTermMemory

    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    app = module.HarnessApp(
        agent, ShortTermMemory(session_service=sessions), "app", max_llm_calls=2
    ).app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/run_sse",
            json={
                **IDENTITY,
                "new_message": {"role": "user", "parts": [{"text": "hello"}]},
                "streaming": True,
            },
        )
        assert response.status_code >= 400 or "error" in response.text.lower()
    assert not host.requests
