"""Phase boundaries tested with real SDK payloads and synthetic text only."""

from types import SimpleNamespace

import pytest

pytest.importorskip("openai_codex")
from openai_codex.generated import v2_all  # noqa: E402

from veadk.runtime.codex import translate  # noqa: E402


def _note(name, item=None, **fields):
    data = {
        "thread_id": "thread",
        "turn_id": "turn",
        "started_at_ms": 0,
        "completed_at_ms": 1,
        **fields,
    }
    if item is not None:
        data["item"] = item
    return getattr(v2_all, name).model_validate(data)


def _item(phase, text="synthetic message", item_id="item"):
    return {"type": "agentMessage", "id": item_id, "text": text, "phase": phase}


def _visible(events):
    return [
        p.text
        for e in events
        for p in (e.content.parts if e.content else [])
        if p.text and not p.thought
    ]


@pytest.mark.parametrize("phase", [p.value for p in v2_all.MessagePhase] + [None])
def test_complete_preserves_phase_and_only_answer_candidates(phase):
    note = _note("ItemCompletedNotification", _item(phase))
    events = translate.notification_to_events(note, "agent", "inv")
    event = events[0]
    assert "phase" in event.custom_metadata
    assert event.custom_metadata["phase"] == phase
    assert translate.is_codex_final_text_event(event) == (
        phase in (None, "final_answer")
    )
    if phase not in (None, "final_answer"):
        assert event.partial is True
        assert not _visible(events)
        assert event.custom_metadata["text"] == "synthetic message"


@pytest.mark.parametrize("phase", [p.value for p in v2_all.MessagePhase] + [None])
def test_started_delta_completed_correlate_per_item(phase):
    phases = {}

    def emit(note):
        return translate.notification_to_events(
            note, "agent", "inv", item_phases=phases
        )

    started = emit(_note("ItemStartedNotification", _item(phase, text="")))[0]
    assert started.custom_metadata["phase"] == phase
    emit(_note("ItemStartedNotification", _item("commentary", item_id="other")))
    delta = emit(_note("AgentMessageDeltaNotification", item_id="item", delta="chunk"))[
        0
    ]
    assert delta.custom_metadata["phase"] == phase
    assert bool(_visible([delta])) == (phase == "final_answer")
    assert delta.partial is True
    emit(_note("ItemCompletedNotification", _item(phase)))
    assert "item" not in phases
    assert "other" in phases
    # A late delta cannot inherit a completed item's phase.
    late = emit(_note("AgentMessageDeltaNotification", item_id="item", delta="late"))
    assert not _visible(late)


def test_unknown_delta_is_not_an_answer_and_reasoning_stays_thought():
    events = translate.notification_to_events(
        _note("AgentMessageDeltaNotification", item_id="missing", delta="unclassified"),
        "agent",
        "inv",
    )
    assert not _visible(events)
    assert events[0].custom_metadata["text"] == "unclassified"
    thought = translate.notification_to_events(
        _note(
            "ReasoningSummaryTextDeltaNotification",
            item_id="reason",
            summary_index=0,
            delta="synthetic reasoning marker",
        ),
        "agent",
        "inv",
    )[0]
    assert thought.content.parts[0].thought is True


@pytest.mark.parametrize(
    "phases,expected",
    [
        (["commentary", "final_answer"], "message-1"),
        (["partial_answer", "final_answer"], "message-1"),
        ([None, None], "message-1"),
        (["final_answer", None], "message-0"),
        (["final_answer", "final_answer"], "message-1"),
        (["commentary", "partial_answer"], None),
    ],
)
def test_batch_final_selection_matches_codex(phases, expected):
    items = [_item(phase, f"message-{i}", str(i)) for i, phase in enumerate(phases)]
    events = translate.result_to_events(SimpleNamespace(items=items), "agent", "inv")
    durable = [e for e in events if not e.partial]
    assert _visible(durable) == ([] if expected is None else [expected])


def test_unknown_phase_does_not_become_an_answer():
    events = translate.item_to_events(_item("future_phase"), "agent", "inv")
    assert not _visible(events)
    assert events[0].partial is True


def test_final_text_is_not_split_using_keywords():
    text = "Let me think is the title of the requested document."
    event = translate.item_to_events(_item("final_answer", text), "agent", "inv")[0]
    assert _visible([event]) == [text]


def test_empty_explicit_final_does_not_resurrect_an_earlier_message():
    items = [_item(None, "earlier draft", "old"), _item("final_answer", "", "final")]
    events = translate.result_to_events(SimpleNamespace(items=items), "agent", "inv")
    assert _visible(events) == []
    assert events[-1].custom_metadata["phase"] == "final_answer"
