"""ADK projection uses native events, synthetic inputs and local transports only."""

import asyncio
import copy
from contextlib import aclosing

import httpx
import pytest
from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from veadk.runtime.customer import (
    CustomerAdkEventStream,
    CustomerChannelError,
    CustomerToolDispatcher,
)
from tests.runtime.customer.test_channel import call, complete, request, tool
from tests.runtime.customer.test_dispatch import Host


MESSAGE = {"role": "user", "parts": [{"text": "Hello"}]}


def native(*, text=None, **kwargs):
    if text is not None:
        kwargs["content"] = types.Content(role="model", parts=[types.Part(text=text)])
    return Event(author="remote_agent", **kwargs).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )


def wire(run, data):
    return {"type": "run.event", "run_id": run.run_id, "event": data}


def adapter(dispatch, **kwargs):
    return CustomerAdkEventStream(
        dispatch,
        author="local_agent",
        invocation_id="local-invocation",
        new_message=MESSAGE,
        **kwargs,
    )


async def project(records):
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [*(wire(run, item) for item in records), complete(run)])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        async with adapter(dispatch) as stream:
            result = [event async for event in stream.events()]
        assert dispatch.quiescent
    return result


@pytest.mark.asyncio
async def test_native_echo_deltas_final_and_local_identity():
    echo = Event(author="user", content=types.Content(**MESSAGE)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    final = native(text="Hello back", invocation_id="remote-invocation")
    result = await project([echo, native(text="Hello", partial=True), final])
    assert len(result) == 2
    assert result[0].partial and not result[0].is_final_response()
    assert result[1].is_final_response() and result[1].turn_complete
    assert [event.content.parts[0].text for event in result] == ["Hello", "Hello back"]
    assert {event.author for event in result} == {"local_agent"}
    assert {event.invocation_id for event in result} == {"local-invocation"}
    assert result[1].id != final["id"]


@pytest.mark.asyncio
async def test_final_waits_for_terminal_and_cleanup():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, native(text="Answer"))])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        received = []

        async def consume():
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    assert dispatch.quiescent and host.stream.closed
                    received.append(event)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.02)
        assert not received and not task.done()
        host.send(complete(run))
        await asyncio.wait_for(task, 1)
    assert len(received) == 1


def display_call(call_id="remote-call", name="lookup", **kwargs):
    return native(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        id=call_id, name=name, args={"name": "企业"}
                    )
                )
            ],
        ),
        **kwargs,
    )


def display_response(call_id="remote-call", name="lookup"):
    return native(
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=call_id, name=name, response={"pages": [1, 2]}
                    )
                )
            ],
        )
    )


@pytest.mark.asyncio
async def test_remote_actions_and_routing_never_change_local_events():
    raw = native(text="answer")
    raw.update(
        {
            "actions": {
                "stateDelta": {"app:admin": True},
                "transferToAgent": "other",
                "skipSummarization": True,
            },
            "branch": "other.branch",
            "invocationId": "remote",
            "timestamp": 1,
            "isolationScope": "remote",
            "customMetadata": {"private": "synthetic-private"},
            "output": {"private": "synthetic-private"},
            "nodeInfo": {"path": "remote/node"},
            "liveSessionId": "synthetic-private",
        }
    )
    result = (await project([raw]))[0]
    assert not result.actions.state_delta
    assert result.actions.transfer_to_agent is None
    assert not result.actions.skip_summarization
    assert result.branch is None and result.isolation_scope is None
    assert result.timestamp != 1 and not result.node_info.path
    assert result.custom_metadata is None and result.output is None
    assert "synthetic-private" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_display_tool_pairs_are_remapped_and_never_executed():
    records = [display_call(), display_response(), native(text="done")]
    result = await project(records)
    function = result[0].get_function_calls()[0]
    response = result[1].get_function_responses()[0]
    assert function.id == response.id and function.id != "remote-call"
    assert function.args == {"name": "企业"}
    assert response.response == {"pages": [1, 2]}
    assert not result[0].is_final_response() and not result[1].is_final_response()
    second = await project(records)
    assert second[0].get_function_calls()[0].id != function.id


@pytest.mark.asyncio
async def test_usage_copied_once_and_thought_does_not_look_final():
    thought = native(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    text="reasoning",
                    thought=True,
                    thought_signature=b"synthetic-signature",
                )
            ],
        )
    )
    usage = {
        "promptTokenCount": 11,
        "candidatesTokenCount": 7,
        "totalTokenCount": 18,
        "cachedContentTokenCount": 3,
        "thoughtsTokenCount": 2,
    }
    delta = native(text="answer", partial=True)
    delta["usageMetadata"] = usage
    final = native(text="answer")
    final["usageMetadata"] = usage
    result = await project([thought, delta, final])
    assert result[0].partial and not result[0].is_final_response()
    assert result[0].content.parts[0].thought_signature is None
    assert result[1].usage_metadata is None
    assert result[2].usage_metadata.total_token_count == 18
    assert result[2].usage_metadata.thoughts_token_count == 2


@pytest.mark.asyncio
async def test_snake_aliases_and_usage_after_final():
    records = [display_call(), display_response(), native(text="answer")]
    records[0]["content"]["parts"][0]["function_call"] = records[0]["content"]["parts"][
        0
    ].pop("functionCall")
    records[1]["content"]["parts"][0]["function_response"] = records[1]["content"][
        "parts"
    ][0].pop("functionResponse")
    usage = native()
    usage["usage_metadata"] = {"total_token_count": 18}
    result = await project([*records, usage])
    assert result[-2].partial and result[-2].usage_metadata.total_token_count == 18
    assert result[-1].is_final_response()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "records,code",
    [
        ([native(text="one"), native(text="two")], "multiple_final_responses"),
        ([native(text="one"), native(text="late", partial=True)], "event_after_final"),
        ([native(text="delta", partial=True)], "missing_final_response"),
        ([display_response()], "invalid_display_tool_response"),
        (
            [display_call(), display_response(name="other")],
            "invalid_display_tool_response",
        ),
        ([display_call(), display_call()], "invalid_display_tool_call"),
        (
            [display_call(), display_response(), display_response()],
            "invalid_display_tool_response",
        ),
        ([display_call(), native(text="done")], "unresolved_display_tools"),
        ([display_call(partial=True)], "unsupported_partial_tool_event"),
        (
            [
                native(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=b"synthetic", mime_type="text/plain"
                                )
                            )
                        ],
                    )
                )
            ],
            "unsupported_adk_content",
        ),
        ([native(long_running_tool_ids={"pending"})], "unsupported_interactive_event"),
        (
            [{**native(), "actions": {"requestedToolConfirmations": {"call": {}}}}],
            "unsupported_interactive_event",
        ),
        (
            [{**native(), "actions": {"requested_auth_configs": {"call": {}}}}],
            "unsupported_interactive_event",
        ),
        ([native(interrupted=True)], "remote_event_interrupted"),
        ([{**native(), "partial": "false"}], "invalid_adk_event"),
        ([{**native(), "id": ""}], "invalid_adk_event"),
        ([{**native(), "usageMetadata": {"totalTokenCount": -1}}], "invalid_adk_event"),
        (
            [{**native(), "usageMetadata": {"totalTokenCount": True}}],
            "invalid_adk_event",
        ),
        (
            [{**native(), "usageMetadata": {"totalTokenCount": 2**53}}],
            "invalid_adk_event",
        ),
        (
            [{**native(), "usageMetadata": {}, "usage_metadata": {}}],
            "invalid_adk_event",
        ),
    ],
)
async def test_bad_remote_event_has_fixed_error(records, code):
    with pytest.raises(CustomerChannelError, match="^" + code + "$"):
        await project(records)


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["different", "duplicate", "late"])
async def test_user_echo_is_not_a_second_input(location):
    echo = Event(author="user", content=types.Content(**MESSAGE)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    second = copy.deepcopy(echo)
    second["id"] = "other-id"
    if location == "different":
        second["content"]["parts"][0]["text"] = "other message"
        records = [second]
    elif location == "duplicate":
        records = [echo, second]
    else:
        records = [native(text="delta", partial=True), echo]
    with pytest.raises(CustomerChannelError, match="unexpected_user_event"):
        await project(records)


@pytest.mark.asyncio
async def test_complete_event_id_duplicate_cannot_be_saved_twice():
    raw = display_call()
    with pytest.raises(CustomerChannelError, match="duplicate_adk_event"):
        await project([raw, raw])


@pytest.mark.asyncio
async def test_error_after_answer_discards_answer_without_echoing_error_body():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, native(text="premature"))])
    emitted = []
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})

        async def fail_host():
            await asyncio.sleep(0.02)
            host.send(
                wire(run, {**native(), "errorMessage": "synthetic-private-error"})
            )
            host.send(complete(run, "error"))

        sender = asyncio.create_task(fail_host())
        with pytest.raises(CustomerChannelError) as caught:
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    emitted.append(event)
        await sender
    assert not emitted
    assert "synthetic-private-error" not in str(caught.value)
    assert dispatch.quiescent and host.stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_ok", [True, False])
async def test_final_waits_for_result_ack_with_different_channel_and_function_ids(
    ack_ok,
):
    run = request(tools=(tool(),)).model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, display_call()), call(run)])
    started = asyncio.Event()
    release = asyncio.Event()
    executed, emitted = [], []

    async def executor(args, request_id):
        executed.append(request_id)
        return {"pages": [1, 2]}

    async def ack(_):
        host.send(wire(run, display_response()))
        host.send(wire(run, native(text="answer")))
        host.send(complete(run))
        started.set()
        await release.wait()
        return httpx.Response(200, json={"accepted": ack_ok})

    host.result_handler = ack
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})

        async def consume():
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    emitted.append(event)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.sleep(0.02)
        assert not any(e.is_final_response() for e in emitted)
        release.set()
        if ack_ok:
            await asyncio.wait_for(task, 1)
        else:
            with pytest.raises(CustomerChannelError, match="result_not_accepted"):
                await asyncio.wait_for(task, 1)
    assert executed == ["call-a"]
    assert len(host.results) == 1 and dispatch.quiescent
    assert sum(e.is_final_response() for e in emitted) == int(ack_ok)


@pytest.mark.asyncio
async def test_cancelled_consumer_cleans_and_same_client_can_run_again():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, native(text="delta", partial=True))])
    entered = asyncio.Event()
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})

        async def consume():
            async with adapter(dispatch) as stream:
                async for _ in stream.events():
                    entered.set()
                    await asyncio.Event().wait()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert dispatch.quiescent and host.cancelled == 1
        next_run = request().model_copy(update={"new_message": MESSAGE})
        from tests.runtime.customer.test_channel import ready
        from tests.runtime.customer.test_dispatch import Stream

        host.stream = Stream(
            [ready(), wire(next_run, native(text="next")), complete(next_run)]
        )
        async with adapter(CustomerToolDispatcher(client, next_run, {})) as stream:
            events = [event async for event in stream.events()]
        assert events[-1].content.parts[0].text == "next"


@pytest.mark.asyncio
async def test_single_context_single_consumer_and_snapshot():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, native(text="done")), complete(run)])
    async with host.client() as client:
        instance = adapter(CustomerToolDispatcher(client, run, {}))
        with pytest.raises(CustomerChannelError, match="event_stream_unavailable"):
            instance.events()
        async with instance:
            iterator = instance.events()
            with pytest.raises(CustomerChannelError, match="event_stream_unavailable"):
                instance.events()
            assert len([event async for event in iterator]) == 1
        with pytest.raises(CustomerChannelError, match="event_stream_unavailable"):
            async with instance:
                pass


class _DisplayAgent(BaseAgent):
    stream_factory: object

    async def _run_async_impl(self, ctx):
        async with self.stream_factory(ctx) as stream:
            async for event in stream.events():
                yield event


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_save", [False, True])
async def test_actual_adk_runner_saves_local_identity_once_and_closes_on_save_failure(
    fail_save,
):
    class Sessions(InMemorySessionService):
        async def append_event(self, session, event):
            if fail_save and event.get_function_responses():
                raise RuntimeError("synthetic storage failure")
            return await super().append_event(session, event)

    service = Sessions()
    await service.create_session(
        app_name="managed_example",
        user_id="user-a",
        session_id="session-a",
        state={"safe": True},
    )
    run = request(tools=(tool(),)).model_copy(update={"new_message": MESSAGE})
    echo = Event(author="user", content=types.Content(**MESSAGE)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    host = Host(run, [wire(run, echo), wire(run, display_call()), call(run)])
    executions, dispatchers = [], []

    async def executor(args, request_id):
        executions.append(request_id)
        return {"pages": [1, 2]}

    async def ack(_):
        response = display_response()
        response["actions"] = {"stateDelta": {"app:admin": True}}
        host.send(wire(run, response))
        if not fail_save:
            host.send(wire(run, native(text="done")))
            host.send(complete(run))
        return httpx.Response(200, json={"accepted": True})

    host.result_handler = ack
    async with host.client() as client:

        def factory(ctx):
            dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})
            dispatchers.append(dispatch)
            return CustomerAdkEventStream(
                dispatch,
                author=ctx.agent.name,
                invocation_id=ctx.invocation_id,
                new_message=ctx.user_content.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                branch=ctx.branch,
            )

        runner = Runner(
            app_name="managed_example",
            agent=_DisplayAgent(name="local_agent", stream_factory=factory),
            session_service=service,
        )
        output = []

        async def consume():
            async with aclosing(
                runner.run_async(
                    user_id="user-a",
                    session_id="session-a",
                    new_message=types.Content(**MESSAGE),
                )
            ) as events:
                async for event in events:
                    saved = await service.get_session(
                        app_name="managed_example",
                        user_id="user-a",
                        session_id="session-a",
                    )
                    assert event.partial or event.id in {e.id for e in saved.events}
                    output.append(event)

        if fail_save:
            with pytest.raises(RuntimeError, match="synthetic storage failure"):
                await consume()
        else:
            await consume()
        assert dispatchers[0].quiescent and host.stream.closed
    saved = await service.get_session(
        app_name="managed_example", user_id="user-a", session_id="session-a"
    )
    assert sum(e.author == "user" for e in saved.events) == 1
    assert saved.state == {"safe": True}
    assert all(e.author in {"user", "local_agent"} for e in saved.events)
    assert executions == ["call-a"] and len(host.results) == 1
    assert sum(e.is_final_response() for e in output) == int(not fail_save)


def projector(**kwargs):
    from veadk.runtime.customer.events import _Projector

    return _Projector(
        **{
            "author": "local_agent",
            "invocation_id": "local-invocation",
            "new_message": MESSAGE,
            "branch": None,
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"author": "user"},
        {"author": ""},
        {"invocation_id": ""},
        {"branch": "bad\nbranch"},
        {"new_message": {}},
        {"new_message": {"role": "user", "parts": [{"text": ""}]}},
        {
            "new_message": {
                "role": "user",
                "parts": [{"inlineData": {"data": "synthetic"}}],
            }
        },
    ],
)
def test_invalid_local_configuration_rejected_before_network(kwargs):
    with pytest.raises(ValueError):
        projector(**kwargs)


def test_input_snapshot_and_local_branch_are_retained():
    message = copy.deepcopy(MESSAGE)
    p = projector(new_message=message, branch="local.branch")
    message["parts"][0]["text"] = "changed after construction"
    echo = Event(author="user", content=types.Content(**MESSAGE)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert p.project(echo) is None
    p.project(native(text="done"))
    assert p.finish().branch == "local.branch"


def test_limits_apply_to_real_event_bytes_and_event_count():
    p = projector()
    with pytest.raises(CustomerChannelError, match="adk_event_too_large"):
        p.project(native(text="x" * (1024 * 1024)))
    p = projector()
    raw = native(text="chunk", partial=True)
    for _ in range(4096):
        assert p.project(raw).partial
    with pytest.raises(CustomerChannelError, match="too_many_adk_events"):
        p.project(raw)


def test_display_call_limits_include_finished_and_pending_calls():
    p = projector()
    for i in range(64):
        p.project(display_call(call_id=str(i)))
    with pytest.raises(CustomerChannelError, match="invalid_display_tool_call"):
        p.project(display_call(call_id="overflow"))
    p = projector()
    for i in range(1024):
        p.project(display_call(call_id=str(i)))
        p.project(display_response(call_id=str(i)))
    with pytest.raises(CustomerChannelError, match="invalid_display_tool_call"):
        p.project(display_call(call_id="overflow"))


@pytest.mark.parametrize(
    "data,code",
    [
        ([], "invalid_adk_event"),
        ({**native(), "content": {"role": "system", "parts": []}}, "invalid_adk_event"),
        ({**native(), "content": {"role": "model", "parts": [1]}}, "invalid_adk_event"),
        (
            {**native(), "content": {"role": "model", "parts": [{}]}},
            "unsupported_adk_content",
        ),
        (
            {**native(), "content": {"role": "model", "parts": [{"text": 3}]}},
            "invalid_adk_event",
        ),
        (
            {
                **native(),
                "content": {
                    "role": "model",
                    "parts": [{"text": "a", "thought": "yes"}],
                },
            },
            "invalid_adk_event",
        ),
        (
            {
                **native(),
                "content": {
                    "role": "model",
                    "parts": [{"text": "a", "functionCall": {}}],
                },
            },
            "unsupported_adk_content",
        ),
        (
            {
                **native(),
                "content": {
                    "role": "model",
                    "parts": [{"function_call": {}, "functionCall": {}}],
                },
            },
            "invalid_adk_event",
        ),
        (
            {**native(), "content": {"role": "user", "parts": [{"text": "spoof"}]}},
            "invalid_adk_event",
        ),
        (
            {**native(), "content": {"role": "user", "parts": [{"functionCall": {}}]}},
            "invalid_display_tool_call",
        ),
        (
            {
                **native(),
                "content": {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "lookup", "args": {}}}],
                },
            },
            "invalid_display_tool_call",
        ),
        ({**native(), "actions": [1]}, "invalid_adk_event"),
        ({**native(), "usageMetadata": [1]}, "invalid_adk_event"),
        (
            {
                **native(),
                "usageMetadata": {"totalTokenCount": 1, "total_token_count": 1},
            },
            "invalid_adk_event",
        ),
        ({**native(text="a"), "turnComplete": "yes"}, "invalid_adk_event"),
        ({**native(), "customMetadata": {"not-json": object()}}, "invalid_adk_event"),
        (
            {**native(), "customMetadata": {"not-finite": float("nan")}},
            "invalid_adk_event",
        ),
        ({**native(), "errorMessage": "synthetic-private"}, "remote_event_error"),
    ],
)
def test_projector_rejects_malformed_values_without_echoing_payload(data, code):
    with pytest.raises(CustomerChannelError, match="^" + code + "$"):
        projector().project(data)


def test_empty_content_needs_explicit_completion_and_metadata_is_not_final():
    p = projector()
    assert p.project(native()) is None
    assert p.project({**native(), "usageMetadata": {"ignored": "synthetic"}}) is None
    p.project(native(content=types.Content(role="model", parts=[]), turn_complete=True))
    assert p.finish().is_final_response()
    p = projector()
    assert p.project(native(content=types.Content(role="model", parts=[]))).partial
    with pytest.raises(CustomerChannelError, match="missing_final_response"):
        p.finish()


@pytest.mark.parametrize("role,parts", [([], []), ({}, []), ("user", [])])
def test_malformed_or_empty_user_role_cannot_be_projected_as_answer(role, parts):
    with pytest.raises(CustomerChannelError, match="^invalid_adk_event$"):
        projector().project(
            {
                **native(),
                "content": {"role": role, "parts": parts},
                "turnComplete": True,
            }
        )


@pytest.mark.asyncio
async def test_cleanup_failure_after_terminal_still_prevents_final(monkeypatch):
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, native(text="answer")), complete(run)])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        close = dispatch.aclose

        async def fail_close(**kwargs):
            await close(**kwargs)
            raise CustomerChannelError("cleanup_timeout")

        monkeypatch.setattr(dispatch, "aclose", fail_close)
        emitted = []
        with pytest.raises(CustomerChannelError, match="cleanup_timeout"):
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    emitted.append(event)
        assert not emitted and dispatch.quiescent


@pytest.mark.asyncio
async def test_early_exit_and_cross_task_iteration_are_rejected_and_cleaned():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        async with adapter(dispatch) as stream:

            async def cross_task():
                stream.events()

            with pytest.raises(
                CustomerChannelError, match="event_stream_task_mismatch"
            ):
                await asyncio.create_task(cross_task())
        assert dispatch.quiescent


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["cancelled", "eof"])
async def test_cancelled_or_incomplete_host_does_not_publish_held_answer(ending):
    from tests.runtime.customer.test_channel import Stream as FiniteStream, ready

    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [])
    events = [ready(), wire(run, native(text="answer"))]
    if ending == "cancelled":
        events.append(complete(run, "cancelled"))
    host.stream = FiniteStream(events)
    emitted = []
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        with pytest.raises(CustomerChannelError):
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    emitted.append(event)
        assert dispatch.quiescent
    assert not emitted
