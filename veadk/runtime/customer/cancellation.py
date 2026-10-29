"""Server-confirmed cancellation and display-only history settlement."""

from dataclasses import dataclass

from google.adk.events import Event
from google.genai import types

from .protocol import CustomerChannelError
from .session_store import CustomerSessionBinding, CustomerTurnRecord


@dataclass(frozen=True, repr=False)
class CustomerCancellationContext:
    """Trusted identities for one reserved turn; contains no transport headers."""

    local_identity: tuple[str, str, str]
    invocation_id: str
    binding: CustomerSessionBinding
    turn: CustomerTurnRecord


def cancellation_events(journal, *, author, invocation_id, next_timestamp):
    """Pair unresolved calls without retrying them or inventing their effects."""
    pending = {}
    for event in journal:
        for call in event.get_function_calls():
            if not call.id or call.id in pending:
                raise CustomerChannelError("cancellation_history_conflict")
            pending[call.id] = call
        for response in event.get_function_responses():
            call = pending.pop(response.id, None)
            if call is None or call.name != response.name:
                raise CustomerChannelError("cancellation_history_conflict")
    events = []
    if pending:
        events.append(
            Event(
                author=author,
                invocation_id=invocation_id,
                timestamp=next_timestamp(),
                content=types.UserContent(
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=call.id,
                                name=call.name,
                                response={
                                    "error": "customer_turn_cancelled",
                                    "side_effects": "unknown",
                                },
                            )
                        )
                        for call in pending.values()
                    ]
                ),
            )
        )
    events.append(
        Event(
            author=author,
            invocation_id=invocation_id,
            timestamp=next_timestamp(),
            interrupted=True,
            turn_complete=True,
            error_code="customer_turn_cancelled",
            content=types.ModelContent(
                parts=[types.Part(text="Request cancelled by the user.")]
            ),
        )
    )
    return events
