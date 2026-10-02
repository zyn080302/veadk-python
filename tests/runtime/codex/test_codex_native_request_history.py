"""State-only ADK events must not duplicate a fresh native user turn."""

from types import SimpleNamespace

import pytest
from google.adk.events import Event
from google.genai import types

from veadk.runtime.model_callbacks import _build_request_contents


@pytest.mark.parametrize("trailing", ["state", "partial", "internal_tool"])
def test_current_user_after_invisible_event_is_included_once(trailing):
    current = types.Content(role="user", parts=[types.Part(text="exact task")])
    user = Event(author="user", invocation_id="current", content=current)
    tail = Event(author="agent", invocation_id="current")
    if trailing == "partial":
        tail.partial = True
        tail.content = types.Content(role="model", parts=[types.Part(text="progress")])
    elif trailing == "internal_tool":
        from veadk.runtime.model_callbacks import _INTERNAL_TOOL_NAMES

        tail.content = types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name=next(iter(_INTERNAL_TOOL_NAMES)), args={}
                    )
                )
            ],
        )
    ctx = SimpleNamespace(
        user_content=current,
        invocation_id="current",
        session=SimpleNamespace(events=[user, tail]),
    )
    contents = _build_request_contents(None, ctx)
    assert contents == [current]
    assert ctx.session.events == [user, tail]


def test_identical_older_user_message_is_not_removed():
    current = types.Content(role="user", parts=[types.Part(text="repeat task")])
    previous = Event(
        author="user", invocation_id="previous", content=current.model_copy(deep=True)
    )
    ctx = SimpleNamespace(
        user_content=current,
        invocation_id="current",
        session=SimpleNamespace(events=[previous]),
    )
    assert _build_request_contents(None, ctx) == [current, current]


def test_visible_intervening_result_and_repeated_history_survive():
    current = types.Content(role="user", parts=[types.Part(text="repeat task")])
    prior = Event(author="user", invocation_id="old", content=current)
    result = types.Content(role="model", parts=[types.Part(text="prior result")])
    reply = Event(author="agent", invocation_id="old", content=result)
    user = Event(author="user", invocation_id="current", content=current)
    state = Event(author="agent", invocation_id="current")
    ctx = SimpleNamespace(
        user_content=current,
        invocation_id="current",
        session=SimpleNamespace(events=[prior, reply, user, state]),
    )
    assert _build_request_contents(None, ctx) == [current, result, current]
