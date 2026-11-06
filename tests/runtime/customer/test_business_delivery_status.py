"""Whitelist business status through real dispatcher and durable ADK events."""

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
DELIVERY = {
    "version": 1,
    "model_reported": True,
    "outcome": "partial",
    "requirements": 2,
    "unknown": 1,
}


def delivered(alias="customMetadata", **changes):
    raw = native(text="Verified field; missing field explicitly unknown.")
    raw[alias] = {"skyeyes_research_delivery": {**DELIVERY, **changes}}
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["customMetadata", "custom_metadata"])
@pytest.mark.parametrize(
    "outcome,unknown", [("partial", 1), ("answer", 0), ("clarification", 2)]
)
async def test_delivery_survives_real_dispatch_with_fresh_local_identity(
    alias, outcome, unknown
):
    raw = delivered(alias, outcome=outcome, unknown=unknown)
    raw[alias]["identity"] = {"author": "synthetic-private", "approval": True}
    raw["actions"] = {"stateDelta": {"synthetic_private": "never imported"}}
    before = copy.deepcopy(raw)
    (final,) = await project([raw])
    assert final.custom_metadata == {
        "skyeyes_research_delivery": {
            **DELIVERY,
            "outcome": outcome,
            "unknown": unknown,
        }
    }
    assert final.turn_complete and not final.partial
    assert final.author == "local_agent" and final.invocation_id == "local-invocation"
    assert final.id != raw["id"] and not final.actions.state_delta
    assert "synthetic-private" not in final.model_dump_json()
    final.custom_metadata["skyeyes_research_delivery"]["unknown"] = 0
    assert raw == before


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {},
        {**DELIVERY, "version": True},
        {**DELIVERY, "model_reported": 1},
        {**DELIVERY, "outcome": "synthetic-private"},
        {**DELIVERY, "requirements": True},
        {**DELIVERY, "requirements": 129},
        {**DELIVERY, "unknown": -1},
        {**DELIVERY, "unknown": 3},
        {**DELIVERY, "unknown": 0},
        {**DELIVERY, "outcome": "answer"},
        {**DELIVERY, "authority": True},
    ],
)
def test_reserved_delivery_rejects_malformed_values_without_echo(marker):
    raw = delivered()
    raw["customMetadata"]["skyeyes_research_delivery"] = marker
    with pytest.raises(CustomerChannelError, match="^invalid_research_delivery$"):
        _Projector(
            author="local", invocation_id="local", new_message=MESSAGE, branch=None
        ).project(raw)


@pytest.mark.parametrize(
    "change", ["partial", "nonterminal", "thought", "tool", "user", "empty", "aliases"]
)
def test_delivery_cannot_certify_draft_thought_tool_user_or_empty_event(change):
    raw = delivered()
    if change == "partial":
        raw["partial"] = True
    elif change == "nonterminal":
        raw["turnComplete"] = False
    elif change == "thought":
        raw["content"]["parts"][0]["thought"] = True
    elif change == "tool":
        raw["content"]["parts"] = [
            {"functionCall": {"id": "call", "name": "lookup", "args": {}}}
        ]
    elif change == "user":
        raw.update(author="user", content=copy.deepcopy(MESSAGE))
    elif change == "empty":
        raw.pop("content")
    else:
        raw["custom_metadata"] = copy.deepcopy(raw["customMetadata"])
    with pytest.raises(CustomerChannelError):
        _Projector(
            author="local", invocation_id="local", new_message=MESSAGE, branch=None
        ).project(raw)


@pytest.mark.asyncio
async def test_partial_prefix_waits_for_cleanup_and_transport_failure_never_releases_final():
    run = request().model_copy(update={"new_message": MESSAGE})
    prefix = native(text="Verified field; ", partial=True)
    host = Host(run, [wire(run, prefix)])
    async with host.client() as client:
        dispatch = CustomerToolDispatcher(client, run, {})
        async with adapter(dispatch) as stream:
            iterator = stream.events()
            first = await anext(iterator)
            assert first.partial and not dispatch.quiescent
            host.send(wire(run, delivered()))

            async def finish():
                await asyncio.sleep(0.02)
                assert not dispatch.quiescent
                host.send(complete(run))

            release = asyncio.create_task(finish())
            final = await anext(iterator)
            await release
            assert dispatch.quiescent and host.stream.closed
            assert final.custom_metadata == {"skyeyes_research_delivery": DELIVERY}
    with pytest.raises(CustomerChannelError):
        host = Host(run, [wire(run, delivered()), complete(run, "error")])
        async with host.client() as client:
            async with adapter(CustomerToolDispatcher(client, run, {})) as stream:
                assert [event async for event in stream.events()] == []


@pytest.mark.asyncio
async def test_journal_preserves_partial_until_display_ack_then_allows_independent_next_turn(
    stores,
):
    (final,) = await project([delivered()])
    async with await claim(stores[0]) as lease:
        await lease.begin_turn(final.invocation_id, DIGEST)
        await lease.append_event(final)
        await lease.complete_turn()
        (stored,) = await lease.read_completed(final.invocation_id)
        assert stored.custom_metadata == {"skyeyes_research_delivery": DELIVERY}
        assert stored.model_dump(mode="json") == final.model_dump(mode="json")
        await lease.acknowledge_display()
        await lease.begin_turn("independent-next-invocation", DIGEST)
