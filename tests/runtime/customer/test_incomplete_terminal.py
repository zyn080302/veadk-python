"""Business incompleteness survives real ADK serialization and SDK dispatch."""

import asyncio
import copy

import pytest

from veadk.runtime.customer import CustomerChannelError, CustomerToolDispatcher
from veadk.runtime.customer.events import _Projector
from tests.runtime.customer.test_channel import complete, request
from tests.runtime.customer.test_dispatch import Host
from tests.runtime.customer.test_events import MESSAGE, adapter, native, project, wire
from tests.runtime.customer.test_session_store import (
    stores as store_pair_fixture,
    claim,
    DIGEST,
)


stores = store_pair_fixture

REASONS = (
    "model_tool_protocol_error",
    "host_turn_budget_exhausted",
    "research_delivery_review_rejected",
)
RESULT = {"status": "incomplete", "reason": REASONS[0]}
PURPOSE = {"skyeyes_output_purpose": {"version": 1, "purpose": "final_answer"}}


def stopped(*, alias="customMetadata", reason=REASONS[0], text="Public stop notice"):
    raw = native(text=text, turn_complete=True)
    raw[alias] = {"skyeyes_result": {"status": "incomplete", "reason": reason}}
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["customMetadata", "custom_metadata"])
@pytest.mark.parametrize("reason", REASONS)
async def test_incomplete_marker_survives_with_local_identity_and_fresh_copy(
    alias, reason
):
    raw = stopped(alias=alias, reason=reason)
    raw[alias]["private_state"] = {"auth": "synthetic-private"}
    snapshot = copy.deepcopy(raw)
    (final,) = await project([raw])
    assert final.custom_metadata == {
        "skyeyes_result": {"status": "incomplete", "reason": reason}
    }
    assert final.turn_complete and not final.partial
    assert final.author == "local_agent" and final.invocation_id == "local-invocation"
    assert final.id != raw["id"] and raw == snapshot
    assert "synthetic-private" not in final.model_dump_json()
    final.custom_metadata["skyeyes_result"]["status"] = "changed"
    assert raw[alias]["skyeyes_result"]["status"] == "incomplete"


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["contentless", "empty"])
async def test_status_only_incomplete_is_held_final_not_missing_or_success(shape):
    raw = stopped(text=None)
    if shape == "empty":
        raw["content"] = {"role": "model", "parts": []}
    (final,) = await project([raw])
    assert final.custom_metadata == {"skyeyes_result": RESULT}
    assert final.turn_complete and final.is_final_response()
    assert final.content is None or final.content.parts == []


@pytest.mark.asyncio
async def test_prefix_is_incremental_but_incomplete_waits_for_transport_cleanup():
    run = request().model_copy(update={"new_message": MESSAGE})
    delta = native(text="Visible prefix", partial=True, custom_metadata=PURPOSE)
    host = Host(run, [wire(run, delta)])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        async with adapter(dispatch) as stream:
            iterator = stream.events()
            first = await anext(iterator)
            assert first.partial and first.content.parts[0].text == "Visible prefix"
            assert not host.stream.closed and not dispatch.quiescent
            host.send(wire(run, stopped()))

            # Same owner task consumes the iterator; the independent Host
            # confirms no final escaped before run.completed.
            async def release():
                await asyncio.sleep(0.02)
                assert not dispatch.quiescent
                host.send(complete(run))

            release_task = asyncio.create_task(release())
            final = await anext(iterator)
            await release_task
            assert dispatch.quiescent and host.stream.closed
            assert final.custom_metadata == {"skyeyes_result": RESULT}
            assert final.content.parts[0].text == "Public stop notice"


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {},
        {"status": "complete", "reason": REASONS[0]},
        {"status": "incomplete", "reason": "synthetic-private"},
        {"status": "incomplete", "reason": True},
        {**RESULT, "identity": "synthetic-private"},
    ],
)
def test_malformed_reserved_result_fails_without_echoing_values(marker):
    raw = stopped()
    raw["customMetadata"]["skyeyes_result"] = marker
    with pytest.raises(CustomerChannelError, match="^invalid_result_status$"):
        _Projector(
            author="local", invocation_id="local", new_message=MESSAGE, branch=None
        ).project(raw)


@pytest.mark.parametrize(
    "change", ["partial", "not_terminal", "thought", "tool", "user", "aliases"]
)
def test_incomplete_marker_cannot_claim_drafts_tools_user_or_ambiguous_metadata(change):
    raw = stopped()
    if change == "partial":
        raw["partial"] = True
    elif change == "not_terminal":
        raw.pop("turnComplete")
    elif change == "thought":
        raw["content"]["parts"][0]["thought"] = True
    elif change == "tool":
        raw["content"]["parts"] = [
            {"functionCall": {"name": "lookup", "id": "call", "args": {}}}
        ]
    elif change == "user":
        raw.update(author="user", content=copy.deepcopy(MESSAGE))
    else:
        raw["custom_metadata"] = copy.deepcopy(raw["customMetadata"])
    with pytest.raises(CustomerChannelError):
        _Projector(
            author="local", invocation_id="local", new_message=MESSAGE, branch=None
        ).project(raw)


@pytest.mark.asyncio
async def test_late_status_only_marker_does_not_override_an_already_held_final():
    with pytest.raises(CustomerChannelError, match="multiple_final_responses"):
        await project([native(text="Complete"), stopped(text=None)])


@pytest.mark.asyncio
async def test_transport_failure_discards_held_incomplete_and_normal_run_stays_independent():
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, stopped())])
    async with host.client(turn_timeout=0.05) as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        received = []
        with pytest.raises(CustomerChannelError):
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    received.append(event)
        assert received == [] and dispatch.quiescent
    (final,) = await project([native(text="Complete")])
    assert final.turn_complete and final.custom_metadata is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker",
    [
        RESULT,
        None,
        {**RESULT, "private": True},
        {**RESULT, "reason": "synthetic-private"},
        {**RESULT, "status": "complete"},
    ],
)
async def test_contentless_journal_terminal_requires_exact_marker_and_preserves_readback(
    stores, marker
):
    from google.adk.events import Event

    event = Event(
        author="local_agent",
        invocation_id="invocation-a",
        turn_complete=True,
        custom_metadata={"skyeyes_result": marker} if marker is not None else None,
    )
    async with await claim(stores[0]) as lease:
        await lease.begin_turn("invocation-a", DIGEST)
        await lease.append_event(event)
        if marker != RESULT:
            with pytest.raises(CustomerChannelError, match="^missing_final_response$"):
                await lease.complete_turn()
        else:
            await lease.complete_turn()
            (stored,) = await lease.read_completed("invocation-a")
            assert stored.custom_metadata == {"skyeyes_result": RESULT}
            await lease.acknowledge_display()
            await lease.begin_turn("invocation-b", DIGEST)
