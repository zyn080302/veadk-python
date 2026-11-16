"""Exact-owner failed-turn settlement; never retry remote execution."""
from dataclasses import dataclass
from datetime import datetime, timezone

import anyio

from google.adk.events import Event
from google.genai import types

from .protocol import CustomerChannelError
from .runtime import _DisplayClock, _event_payload, _read_session, _saved_prefix


@dataclass(frozen=True, repr=False)
class CustomerFailureContext:
    local_identity: tuple
    invocation_id: str
    binding: object
    turn: object
    reason: str = "customer_turn_failed"


def verify_failed_history(journal, invocation_id):
    """Every executed call needs its own known receipt; no invented pairing."""
    pending, seen = {}, set()
    for event in journal:
        if event.invocation_id != invocation_id or event.turn_complete:
            raise CustomerChannelError("failure_history_conflict")
        for call in event.get_function_calls():
            if not call.id or call.id in seen:
                raise CustomerChannelError("failure_history_conflict")
            seen.add(call.id)
            pending[call.id] = call
        for response in event.get_function_responses():
            call = pending.pop(response.id, None)
            if call is None or call.name != response.name or _unknown_effect(response.response):
                raise CustomerChannelError("failure_history_conflict")
    if pending:
        raise CustomerChannelError("failure_history_conflict")


def _unknown_effect(value):
    if isinstance(value, dict):
        return value.get("side_effects") == "unknown" or any(_unknown_effect(v) for v in value.values())
    if isinstance(value, list):
        return any(_unknown_effect(v) for v in value)
    return False


async def settle_failure(config, lease, ctx, context, author, initial_history):
    # Validate local execution history BEFORE requesting Host settlement. A
    # missing receipt is not evidence that an external action did not happen.
    journal = await lease.read_running(context.invocation_id)
    verify_failed_history(journal, context.invocation_id)
    session = await _read_session(ctx.session_service, context.local_identity, config.operation_timeout)
    prefix = _saved_prefix(journal, session)
    if [_event_payload(e) for e in session.events] != [
        *initial_history, *[_event_payload(e) for e in journal[:prefix]]
    ]:
        raise CustomerChannelError("failure_history_conflict")
    # Existing SkyEyes factory routes this exact failure reason through its
    # trusted server callback. Prefer an explicitly supplied failure callback;
    # retain that reviewed compatibility path, never treat cancellation as proof.
    confirmer = config.confirm_failure or config.confirm_cancellation
    if confirmer is None or await confirmer(context) is not True:
        return None
    clock = _DisplayClock(session)
    for event in journal:
        clock.last = max(clock.last, datetime.fromtimestamp(event.timestamp, tz=timezone.utc))
    terminal = Event(author=author, invocation_id=context.invocation_id,
        timestamp=clock.next_timestamp(), branch=ctx.branch,
        interrupted=True, turn_complete=True, error_code="customer_turn_failed",
        error_message="remote_event_error", content=types.ModelContent(parts=[types.Part(
            text="本轮服务返回错误，查询未完成；已保存记录保留，可在当前会话继续提问。")]))
    await lease.append_event(terminal)
    await lease.fail_turn(context.turn)
    for event in journal[prefix:]:
        with anyio.fail_after(config.operation_timeout):
            await ctx.session_service.append_event(session=session, event=event)
    # Runner saves the terminal after yield. The owner remains unavailable
    # until its exact readback is acknowledged by the caller.
    return terminal
