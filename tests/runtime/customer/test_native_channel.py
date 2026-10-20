"""Native multi-HTTP contracts; synthetic HTTP is not deployed acceptance."""

import asyncio
import copy
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from veadk import Agent
from veadk.runtime.customer import (
    CustomerAdkEventStream,
    CustomerChannelClient,
    CustomerChannelError,
    CustomerRunRequest,
    CustomerToolDispatcher,
)
from tests.runtime.customer.test_channel import Stream, tool
from tests.runtime.customer.test_runtime import setup as runtime_setup, turn

setup = runtime_setup


CONFIG = SecretStr(json.dumps({"name": "fixture", "model_name": "fixture-model"}))


def request(**changes):
    return CustomerRunRequest(
        app_name="managed_fixture",
        user_id="fixture-user",
        session_id="fixture-session",
        agent_config=CONFIG,
        new_message={"role": "user", "parts": [{"text": "hello"}]},
        **changes,
    )


def event(parts, *, role="model", author="remote", **values):
    return {
        "id": uuid4().hex,
        "author": author,
        "content": {"role": role, "parts": parts},
        **values,
    }


class NativeHost:
    def __init__(self, batches=(2, 1)):
        self.batches = list(batches)
        self.step = 0
        self.requests = []
        self.streams = []
        self.results = []
        self.calls = []
        self.executed = []
        self.mutation = None
        self.block_echo = False
        self.echo_waiting = asyncio.Event()
        self.echo_release = asyncio.Event()
        self.delay = 0

    async def execute(self, args, request_id):
        self.executed.append(request_id)
        await asyncio.sleep(0)
        return {"company": args["name"]}

    async def handle(self, req):
        self.requests.append(req)
        if req.method == "GET":
            return httpx.Response(404, json={})
        body = json.loads(req.content)
        if req.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"id": body["sessionId"]})
        assert req.url.path == "/run_sse"
        assert "environment" not in body and "payload" not in body
        assert "source" not in json.dumps(body["harness_config"]["studio_tools"])
        message = body["newMessage"]
        output = []
        if "functionResponse" in message["parts"][0]:
            self.results.append(copy.deepcopy(message))
            output.append(event(message["parts"], role="user", author="user"))
        else:
            self.step = 0
        if self.step < len(self.batches):
            calls = [
                {"id": uuid4().hex, "name": "lookup", "args": {"name": "example"}}
                for _ in range(self.batches[self.step])
            ]
            self.calls.extend(calls)
            output.append(
                event(
                    [{"functionCall": c} for c in calls],
                    longRunningToolIds=[c["id"] for c in calls],
                )
            )
        else:
            output.append(event([{"text": "answer"}]))
        self.step += 1
        if self.mutation:
            self.mutation(output)
        owner = self

        class ControlledStream(Stream):
            async def __aiter__(self):
                if owner.block_echo and owner.results:
                    owner.echo_waiting.set()
                    await owner.echo_release.wait()
                if owner.delay:
                    await asyncio.sleep(owner.delay)
                async for chunk in super().__aiter__():
                    yield chunk

        stream = ControlledStream(output)
        self.streams.append(stream)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    def client(self, **kw):
        return CustomerChannelClient(
            "https://fixture.invalid",
            protocol="native",
            transport=httpx.MockTransport(self.handle),
            **kw,
        )


async def collect(host, run=None, *, concurrency=1, **client_options):
    run = run or request(tools=(tool(),))
    async with host.client(**client_options) as client:
        async with CustomerToolDispatcher(
            client,
            run,
            {"lookup": host.execute} if run.tools else {},
            max_concurrency=concurrency,
        ) as dispatch:
            return [e async for e in dispatch.events()]


@pytest.mark.asyncio
async def test_multiple_batches_exceeding_slots_wait_for_real_ack_and_project():
    host = NativeHost()
    run = request(tools=(tool(),))
    async with host.client() as client:
        async with CustomerAdkEventStream(
            CustomerToolDispatcher(
                client, run, {"lookup": host.execute}, max_concurrency=1
            ),
            author="local",
            invocation_id="fixture-invocation",
            new_message=run.new_message,
        ) as projection:
            output = await asyncio.wait_for(_events(projection), 2)
    assert output[-1].turn_complete and output[-1].content.parts[0].text == "answer"
    assert len(host.requests) == 3 and len(host.executed) == 3
    assert len(set(host.executed)) == 3
    assert [len(r["parts"]) for r in host.results] == [2, 1]
    assert sum(len(e.get_function_calls()) for e in output) == 3
    assert sum(len(e.get_function_responses()) for e in output) == 3
    assert all(s.closed for s in host.streams)


async def _events(projection):
    return [event async for event in projection.events()]


@pytest.mark.asyncio
async def test_submit_is_pending_until_validated_echo():
    host = NativeHost((1,))
    host.block_echo = True
    task = asyncio.create_task(collect(host))
    try:
        await asyncio.wait_for(host.echo_waiting.wait(), 1)
        assert len(host.executed) == 1 and not task.done()
        host.echo_release.set()
        assert (await task)[-1]["type"] == "run.completed"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "name", "id", "result", "duplicate"])
async def test_wrong_echo_never_acknowledges_or_reexecutes(mutation):
    host = NativeHost((1,))

    def mutate(output):
        if output[0]["author"] != "user":
            return
        response = output[0]["content"]["parts"][0]["functionResponse"]
        if mutation == "missing":
            output.pop(0)
        elif mutation == "duplicate":
            output.insert(1, copy.deepcopy(output[0]))
        else:
            response[{"name": "name", "id": "id", "result": "response"}[mutation]] = (
                "wrong"
            )

    host.mutation = mutate
    with pytest.raises(CustomerChannelError):
        await collect(host)
    assert len(host.executed) == 1 and len(host.requests) == 2
    assert all(s.closed for s in host.streams)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["name", "args", "ids", "partial", "duplicate", "error"]
)
async def test_invalid_deferred_event_fails_before_execution(mutation):
    host = NativeHost((1,))

    def mutate(output):
        raw = output[0]
        call = raw["content"]["parts"][0]["functionCall"]
        if mutation == "name":
            call["name"] = "unregistered"
        elif mutation == "args":
            call["args"] = {"name": 3}
        elif mutation == "ids":
            raw["longRunningToolIds"] = ["wrong"]
        elif mutation == "partial":
            raw["partial"] = True
        elif mutation == "duplicate":
            raw["content"]["parts"].append(copy.deepcopy(raw["content"]["parts"][0]))
        else:
            raw["errorMessage"] = "untrusted diagnostic"

    host.mutation = mutate
    with pytest.raises(CustomerChannelError) as error:
        await collect(host)
    assert "untrusted diagnostic" not in str(error.value)
    assert host.executed == [] and len(host.requests) == 1


@pytest.mark.asyncio
async def test_one_deadline_covers_all_http_steps():
    host = NativeHost((1, 1, 1))
    host.delay = 0.03
    with pytest.raises(CustomerChannelError, match="run_timeout"):
        await collect(host, turn_timeout=0.07)
    assert 1 <= len(host.executed) < 3
    assert all(s.closed for s in host.streams)


@pytest.mark.asyncio
async def test_cancel_while_ack_pending_closes_without_shared_cancel_or_replay():
    host = NativeHost((1,))
    host.block_echo = True
    task = asyncio.create_task(collect(host))
    await asyncio.wait_for(host.echo_waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(host.executed) == 1 and len(host.requests) == 2
    assert all(s.closed for s in host.streams)


@pytest.mark.asyncio
async def test_native_session_paths_and_unsupported_capabilities():
    host = NativeHost(())
    async with host.client() as client:
        assert not await client.session_exists("managed_fixture", "u", "s")
        await client.create_session("managed_fixture", "u", "s")
        with pytest.raises(CustomerChannelError, match="unsupported_protocol"):
            await client.capabilities()
    assert [r.url.path for r in host.requests] == [
        "/apps/managed_fixture/users/u/sessions/s",
        "/apps/managed_fixture/users/u/sessions",
    ]
    assert all("X-Session-Id" not in r.headers for r in host.requests)


@pytest.mark.asyncio
async def test_native_runtime_mapping_followup_and_protocol_binding(setup):
    config, _, sessions = setup
    host = NativeHost((1,))
    config = replace(
        config,
        protocol="native",
        agent_config=CONFIG,
        tools=(tool(),),
        executors={"lookup": host.execute},
        transport=httpx.MockTransport(host.handle),
    )
    assert replace(config, protocol="shared")._binding_id != config._binding_id
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    for _ in range(2):
        result = await turn(agent, sessions)
        assert result[-1].turn_complete
    assert len([r for r in host.requests if r.method == "GET"]) == 1
    assert len([r for r in host.requests if r.url.path.endswith("/sessions")]) == 1
    agent.customer_runtime_config = replace(config, protocol="shared")
    count = len(host.requests)
    with pytest.raises(CustomerChannelError, match="engine_mismatch"):
        await turn(agent, sessions)
    assert len(host.requests) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("config_value", ["not-json", "[]", "{}", '{"name":NaN}'])
async def test_native_config_rejects_invalid_json_before_io(setup, config_value):
    config, host, _ = setup
    with pytest.raises((ValueError, CustomerChannelError)):
        replace(config, protocol="native", agent_config=SecretStr(config_value))
    assert not host.requests


@pytest.mark.asyncio
async def test_echo_must_preserve_json_scalar_types():
    host = NativeHost((1,))

    async def execute(*_):
        return {"allowed": True}

    def mutate(output):
        if output[0]["author"] == "user":
            output[0]["content"]["parts"][0]["functionResponse"]["response"][
                "allowed"
            ] = 1

    host.execute = execute
    host.mutation = mutate
    with pytest.raises(CustomerChannelError, match="result_not_accepted"):
        await collect(host)


@pytest.mark.asyncio
async def test_results_from_separate_call_events_wait_for_complete_batch():
    host = NativeHost((2,))

    def mutate(output):
        if output[0]["author"] == "user":
            return
        original = output.pop()
        for p in original["content"]["parts"]:
            output.append(event([p], longRunningToolIds=[p["functionCall"]["id"]]))

    async def execute(args, request_id):
        host.executed.append(request_id)
        if len(host.executed) == 2:
            await asyncio.sleep(0.02)
        return {"ok": True}

    host.execute = execute
    host.mutation = mutate
    assert (await collect(host))[-1]["status"] == "success"
    assert len(host.results[0]["parts"]) == 2


@pytest.mark.asyncio
async def test_host_only_tools_are_display_only():
    host = NativeHost(())

    def mutate(output):
        call = {"id": "host-call", "name": "studio_list_skills", "args": {}}
        response = {
            "id": "host-call",
            "name": "studio_list_skills",
            "response": {"skills": []},
        }
        output[0:0] = [
            event([{"functionCall": call}]),
            event([{"functionResponse": response}], role="user"),
        ]

    host.mutation = mutate
    output = await collect(host, request())
    assert output[-1]["status"] == "success"
    assert not host.executed and not host.results


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["empty", "partial", "trailing_error", "after_final"])
async def test_eof_and_final_do_not_hide_failures(kind):
    host = NativeHost(())

    def mutate(output):
        if kind == "empty":
            output.clear()
        elif kind == "partial":
            output[0]["partial"] = True
        elif kind == "trailing_error":
            output.append({"error": "remote details must not leak"})
        else:
            output.append(event([{"text": "second final"}]))

    host.mutation = mutate
    with pytest.raises(CustomerChannelError):
        await collect(host, request())


@pytest.mark.asyncio
async def test_direct_submit_result_stays_pending_and_duplicate_fails():
    host = NativeHost((1,))
    host.block_echo = True
    tasks = []
    async with host.client() as client:
        async with client.run(request(tools=(tool(),))) as channel:

            async def read():
                async for row in channel.events():
                    if row["type"] == "tool.call":
                        tasks.append(
                            asyncio.create_task(
                                channel.submit_result(
                                    row["request_id"], content={"ok": True}
                                )
                            )
                        )

            reader = asyncio.create_task(read())
            try:
                await asyncio.wait_for(host.echo_waiting.wait(), 1)
                assert not tasks[0].done()
                with pytest.raises(CustomerChannelError, match="stale_tool_result"):
                    await channel.submit_result(host.calls[0]["id"], content={})
                host.echo_release.set()
                await reader
                await tasks[0]
            finally:
                reader.cancel()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(reader, *tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_native_callbacks_use_existing_journal_and_serial_state(setup):
    from google.adk.tools import ToolContext
    from tests.runtime.customer.test_runtime import IDENTITY

    config, _, sessions = setup
    host = NativeHost((3,))
    seen = []

    async def lookup(name: str, tool_context: ToolContext):
        value = tool_context.state.get("count", 0) + 1
        seen.append(value)
        tool_context.state["count"] = value
        return {"name": name, "count": value}

    config = replace(
        config,
        protocol="native",
        agent_config=CONFIG,
        native_tools=True,
        tools=(tool(),),
        transport=httpx.MockTransport(host.handle),
        max_concurrency=1,
    )
    agent = Agent(
        name="customer_agent",
        runtime="customer",
        customer_runtime_config=config,
        tools=[lookup],
    )
    result = await turn(agent, sessions)
    assert seen == [1, 2, 3]
    assert sum(len(e.get_function_calls()) for e in result) == 3
    assert sum(len(e.get_function_responses()) for e in result) == 3
    assert (await sessions.get_session(**IDENTITY)).state["count"] == 3


@pytest.mark.asyncio
async def test_invalid_protocol_environment_and_shared_binding_unchanged(setup):
    config, _, _ = setup
    assert replace(config, protocol="shared")._binding_id == config._binding_id
    for protocol in (None, "auto", [], True):
        with pytest.raises(ValueError):
            replace(config, protocol=protocol)
    with pytest.raises(CustomerChannelError, match="invalid_native_configuration"):
        replace(
            config,
            protocol="native",
            agent_config=CONFIG,
            environment={"MODEL": SecretStr("fixture")},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cancelled", "expired"])
async def test_staged_result_revoked_before_next_http_is_never_sent(reason):
    host = NativeHost((1,))
    run = request(tools=(tool(timeout_ms=10 if reason == "expired" else 1000),))
    async with host.client() as client:
        async with client.run(run) as channel:
            submissions = []
            try:
                with pytest.raises(CustomerChannelError, match="stale_tool_result"):
                    async for row in channel.events():
                        if row["type"] == "tool.call":
                            task = asyncio.create_task(
                                channel.submit_result(
                                    row["request_id"], content={"ok": True}
                                )
                            )
                            submissions.append(task)
                            await asyncio.sleep(0)
                            if reason == "cancelled":
                                task.cancel()
                                await asyncio.gather(task, return_exceptions=True)
                            else:
                                await asyncio.sleep(0.03)
                assert len(host.requests) == 1
            finally:
                for task in submissions:
                    task.cancel()
                await asyncio.gather(*submissions, return_exceptions=True)
