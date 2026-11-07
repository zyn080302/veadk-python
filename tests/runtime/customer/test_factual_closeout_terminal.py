"""Factual closeout remains incomplete through real projection and durable replay."""

import asyncio
import copy

import pytest
from google.adk.events import Event

from veadk.runtime.customer import CustomerChannelError, CustomerToolDispatcher
from veadk.runtime.customer.events import _Projector
from tests.runtime.customer.test_channel import complete, request
from tests.runtime.customer.test_dispatch import Host
from tests.runtime.customer.test_events import MESSAGE, adapter, native, project, wire
from tests.runtime.customer.test_incomplete_terminal import stopped
from tests.runtime.customer.test_session_store import (
    DIGEST,
    claim,
    stores as store_pair_fixture,
)


stores = store_pair_fixture
REASONS = (
    "model_tool_protocol_error",
    "host_turn_budget_exhausted",
    "research_delivery_review_rejected",
    "model_request_failed",
    "turn_deadline_exceeded",
    "host_execution_failed",
)
REASON = REASONS[3]
RESULT = {"status": "incomplete", "reason": REASON}


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", REASONS)
@pytest.mark.parametrize("alias", ["customMetadata", "custom_metadata"])
@pytest.mark.parametrize("body", ["public", "empty", "contentless"])
async def test_factual_closeout_serialization_projection_sql_replay_ack_isolation(
    stores, alias, body, reason
):
    raw = stopped(alias=alias, reason=reason, text="Public review stop notice")
    if body == "empty":
        raw["content"] = {"role": "model", "parts": []}
    elif body == "contentless":
        raw.pop("content")
    raw.update(invocationId="remote-invocation", branch="remote.branch")
    raw[alias]["private_state"] = {"admin": True}
    snapshot = copy.deepcopy(raw)
    (projected,) = await project([raw])
    assert raw == snapshot
    assert projected.custom_metadata == {
        "skyeyes_result": {"status": "incomplete", "reason": reason}
    }
    assert projected.author == "local_agent"
    assert projected.invocation_id == "local-invocation"
    assert projected.branch is None and not projected.actions.state_delta
    assert projected.id != raw["id"]
    assert projected.turn_complete and not projected.partial
    # Persist the actual serialized display Event, not a hand-written marker.
    serialized = projected.model_dump_json(by_alias=True, exclude_none=True)
    event = Event.model_validate_json(serialized)
    async with await claim(stores[0]) as lease:
        binding = lease.binding
        await lease.begin_turn("local-invocation", DIGEST)
        wrong_owner = event.model_copy(update={"invocation_id": "other"})
        with pytest.raises(CustomerChannelError, match="^invalid_journal_event$"):
            await lease.append_event(wrong_owner)
        await lease.append_event(event)
        await lease.complete_turn()
        with pytest.raises(CustomerChannelError, match="^display_recovery_required$"):
            await lease.begin_turn("next-invocation", DIGEST)
    # An independently bound user with the same business session sees no data.
    async with await claim(stores[1], ("local-app", "user-b", "session-a")) as other:
        assert other.binding != binding
        assert other.pending_invocation_id is None
        with pytest.raises(CustomerChannelError):
            await other.read_completed("local-invocation")
    await stores[0]._engine.dispose()
    async with await claim(stores[1]) as recovered:
        assert recovered.binding == binding
        assert recovered.pending_invocation_id == "local-invocation"
        (saved,) = await recovered.read_completed("local-invocation")
        assert saved.model_dump() == event.model_dump()
        assert saved.custom_metadata == {
            "skyeyes_result": {"status": "incomplete", "reason": reason}
        }
        saved.custom_metadata["skyeyes_result"]["status"] = "changed"
        assert (await recovered.read_completed("local-invocation"))[
            0
        ].custom_metadata == {
            "skyeyes_result": {"status": "incomplete", "reason": reason}
        }
        await recovered.acknowledge_display()
        assert recovered.pending_invocation_id is None
        await recovered.begin_turn("next-invocation", DIGEST)
        (normal,) = await project([native(text="Independent complete answer")])
        normal = normal.model_copy(update={"invocation_id": "next-invocation"})
        assert normal.custom_metadata is None
        await recovered.append_event(normal)
        await recovered.complete_turn()
        await recovered.acknowledge_display()
        assert (await recovered.read_completed("local-invocation"))[
            0
        ].custom_metadata == {
            "skyeyes_result": {"status": "incomplete", "reason": reason}
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", REASONS)
async def test_factual_closeout_waits_for_terminal_and_cleanup_after_visible_delta(
    reason,
):
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, native(text="Visible prefix", partial=True))])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        async with adapter(dispatch) as stream:
            iterator = stream.events()
            prefix = await anext(iterator)
            assert prefix.partial and not dispatch.quiescent
            host.send(wire(run, stopped(reason=reason)))

            async def release():
                await asyncio.sleep(0.02)
                assert not dispatch.quiescent and not host.stream.closed
                host.send(complete(run))

            release_task = asyncio.create_task(release())
            final = await anext(iterator)
            await release_task
            assert dispatch.quiescent and host.stream.closed
            assert final.custom_metadata == {
                "skyeyes_result": {"status": "incomplete", "reason": reason}
            }


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", REASONS)
async def test_factual_closeout_transport_failure_does_not_release_final(reason):
    run = request().model_copy(update={"new_message": MESSAGE})
    host = Host(run, [wire(run, stopped(reason=reason))])
    async with host.client(turn_timeout=0.05) as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        seen = []
        with pytest.raises(CustomerChannelError):
            async with adapter(dispatch) as stream:
                async for event in stream.events():
                    seen.append(event)
        assert seen == [] and dispatch.quiescent


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", REASONS)
async def test_factual_closeout_cannot_override_a_normal_held_final(reason):
    with pytest.raises(CustomerChannelError, match="^multiple_final_responses$"):
        await project([native(text="Complete answer"), stopped(reason=reason)])


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {},
        {"status": "complete", "reason": REASON},
        {"status": "incomplete", "reason": "unknown-review-reason"},
        {"status": "incomplete", "reason": True},
        {**RESULT, "identity": "forged"},
    ],
)
def test_factual_reason_does_not_relax_reserved_marker_validation(marker):
    raw = stopped(reason=REASON)
    raw["customMetadata"]["skyeyes_result"] = marker
    with pytest.raises(CustomerChannelError, match="^invalid_result_status$"):
        _Projector(
            author="local", invocation_id="local", new_message=MESSAGE, branch=None
        ).project(raw)


@pytest.mark.parametrize(
    "change", ["partial", "nonterminal", "thought", "tool", "user", "aliases"]
)
@pytest.mark.parametrize("reason", REASONS)
def test_factual_reason_does_not_relax_terminal_or_identity_boundary(change, reason):
    raw = stopped(reason=reason)
    if change == "partial":
        raw["partial"] = True
    elif change == "nonterminal":
        raw["turnComplete"] = False
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
