"""Display-purpose isolation through real SDK dispatch and ADK projection."""

import asyncio
import copy

import pytest

from veadk.runtime.customer import (
    CustomerAdkEventStream,
    CustomerChannelError,
    CustomerToolDispatcher,
)
from veadk.runtime.customer.events import _Projector
from tests.runtime.customer.test_channel import complete, request
from tests.runtime.customer.test_dispatch import Host
from tests.runtime.customer.test_events import MESSAGE, adapter, native, project, wire
from tests.runtime.customer.test_native_channel import NativeHost, request as native_run


PURPOSE = {"version": 1, "purpose": "final_answer"}
METADATA = {"skyeyes_output_purpose": PURPOSE}


def marked(raw, alias="customMetadata"):
    raw[alias] = copy.deepcopy(METADATA)
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["customMetadata", "custom_metadata"])
async def test_only_answer_purpose_survives_local_projection(alias):
    delta = marked(native(text="正文", partial=True), alias)
    final = marked(native(text="正文"), alias)
    delta[alias]["private"] = {"token": "synthetic-private"}
    snapshot = copy.deepcopy([delta, final])
    events = await project([delta, final])
    assert [e.custom_metadata for e in events] == [METADATA, METADATA]
    assert events[0].partial and events[-1].turn_complete
    assert {e.author for e in events} == {"local_agent"}
    assert {e.invocation_id for e in events} == {"local-invocation"}
    assert "synthetic-private" not in events[0].model_dump_json()
    assert [delta, final] == snapshot
    events[0].custom_metadata["skyeyes_output_purpose"]["purpose"] = "changed"
    assert events[-1].custom_metadata == METADATA
    assert delta[alias]["skyeyes_output_purpose"] == PURPOSE


@pytest.mark.asyncio
async def test_two_marked_deltas_are_delivered_before_host_completion():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(
        run,
        [wire(run, marked(native(text=t, partial=True))) for t in ("第一段", "第二段")],
    )
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        async with adapter(dispatch) as stream:
            iterator = stream.events()
            first = await anext(iterator)
            second = await anext(iterator)
            assert first.custom_metadata == second.custom_metadata == METADATA
            assert [first.content.parts[0].text, second.content.parts[0].text] == [
                "第一段",
                "第二段",
            ]
            assert first.partial and second.partial
            assert not first.turn_complete and not second.turn_complete
            assert not host.stream.closed and not dispatch.quiescent
            host.send(wire(run, marked(native(text="第一段第二段"))))
            host.send(complete(run))
            final = await anext(iterator)
            assert final.content.parts[0].text == "第一段第二段"
            assert final.custom_metadata == METADATA and final.turn_complete
            assert dispatch.quiescent and host.stream.closed
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)


@pytest.mark.asyncio
async def test_native_channel_preserves_purpose_without_executing_display():
    host = NativeHost(batches=())
    host.mutation = lambda records: [marked(record) for record in records]
    run = native_run()
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        async with CustomerAdkEventStream(
            dispatch,
            author="local_agent",
            invocation_id="local-invocation",
            new_message=run.new_message,
        ) as stream:
            events = [event async for event in stream.events()]
        assert dispatch.quiescent
    assert events[-1].custom_metadata == METADATA and events[-1].turn_complete
    assert not host.executed


@pytest.mark.parametrize(
    "value",
    [
        None,
        "final_answer",
        {},
        {"version": True, "purpose": "final_answer"},
        {"version": 1.0, "purpose": "final_answer"},
        {"version": "1", "purpose": "final_answer"},
        {"version": 2, "purpose": "final_answer"},
        {"version": 1, "purpose": "thought"},
        {"version": 1, "purpose": "final_answer", "approved": True},
        {"version": 1},
        {"purpose": "final_answer"},
    ],
)
def test_malformed_reserved_purpose_fails_without_input_values(value):
    raw = native(text="synthetic-private")
    raw["customMetadata"] = {"skyeyes_output_purpose": value}
    projector = _Projector(
        author="local",
        invocation_id="local-invocation",
        new_message=MESSAGE,
        branch=None,
    )
    with pytest.raises(CustomerChannelError) as caught:
        projector.project(raw)
    assert str(caught.value) == "invalid_output_purpose"
    assert "synthetic-private" not in str(caught.value)


@pytest.mark.parametrize(
    "parts,role,author",
    [
        ([{"text": "reasoning", "thought": True}], "model", "remote"),
        (
            [{"text": "answer"}, {"text": "reasoning", "thought": True}],
            "model",
            "remote",
        ),
        (
            [{"functionCall": {"id": "call", "name": "lookup", "args": {}}}],
            "model",
            "remote",
        ),
        ([], "model", "remote"),
        (MESSAGE["parts"], "user", "user"),
    ],
)
def test_purpose_cannot_promote_thought_tools_user_echo_or_empty_content(
    parts, role, author
):
    raw = marked(native(content={"role": role, "parts": parts}))
    raw["author"] = author
    projector = _Projector(
        author="local",
        invocation_id="local-invocation",
        new_message=MESSAGE,
        branch=None,
    )
    with pytest.raises(CustomerChannelError) as caught:
        projector.project(raw)
    assert str(caught.value) == "invalid_output_purpose"


def test_ambiguous_metadata_aliases_are_rejected():
    raw = marked(native(text="answer"))
    raw["custom_metadata"] = copy.deepcopy(METADATA)
    projector = _Projector(
        author="local",
        invocation_id="local-invocation",
        new_message=MESSAGE,
        branch=None,
    )
    with pytest.raises(CustomerChannelError) as caught:
        projector.project(raw)
    assert str(caught.value) == "invalid_adk_event"


@pytest.mark.asyncio
async def test_cancel_after_marked_delta_preserves_prefix_and_closes_without_final():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, marked(native(text="可见前缀", partial=True)))])
    observed = asyncio.Event()
    events = []
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})

        async def consume():
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    events.append(event)
                    observed.set()

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(observed.wait(), 1)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert dispatch.quiescent and host.stream.closed
    assert len(events) == 1 and events[0].custom_metadata == METADATA
    assert events[0].partial and not events[0].turn_complete
    assert events[0].content.parts[0].text == "可见前缀"
    assert host.cancelled == 1
