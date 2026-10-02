"""Encode an optional application's Responses projection without a tool loop."""

from __future__ import annotations

import json


def rejects_summary(status, message):
    return (
        status == 400
        and 'unknown field "summary"' in str(message).replace('\\"', '"').lower()
    )


class SummaryPreferenceRejected(Exception):
    status_code = 400

    def __init__(self):
        super().__init__('unknown field "summary"')


class SummaryCompatibility:
    """Remember only an explicit refusal of the optional summary preference.

    This is invocation scoped. It never removes historical reasoning items,
    changes effort, or retries unrelated provider failures.
    """

    def __init__(self):
        self._rejected = set()

    async def call(self, backend, **request):
        model = request.get("model")
        while True:
            reasoning = request.get("reasoning")
            if model in self._rejected and isinstance(reasoning, dict):
                request = {
                    **request,
                    "reasoning": {k: v for k, v in reasoning.items() if k != "summary"},
                }
                reasoning = request["reasoning"]
            try:
                return await backend(**request)
            except Exception as error:
                # Read only in local memory. Provider errors can echo inputs;
                # their text must never enter logs, telemetry, or artifacts.
                if (
                    not rejects_summary(
                        getattr(error, "status_code", None),
                        getattr(error, "message", None) or error,
                    )
                    or not isinstance(reasoning, dict)
                    or "summary" not in reasoning
                ):
                    raise
                self._rejected.add(model)


def response_events(response):
    """Deliver a buffered response without inventing deltas or dropping types."""
    status = response.get("status")
    if status not in {"completed", "incomplete", "failed"}:
        raise ValueError("Native response has no terminal status")
    yield {
        "type": "response.created",
        "response": {**response, "output": [], "status": "in_progress"},
    }
    for index, item in enumerate(response.get("output") or []):
        yield {"type": "response.output_item.done", "output_index": index, "item": item}
    yield {"type": "response." + status, "response": response}


async def encode_backend_result(result, adapter=None):
    """Close the owned stream even when the CLI disconnects during projection."""

    def encode(event):
        if not isinstance(event, dict):
            event = event.model_dump(mode="json", exclude_none=True)
        for decoded in adapter.event(event) if adapter else [event]:
            yield f"event: {decoded['type']}\ndata: {json.dumps(decoded)}\n\n".encode()

    try:
        if hasattr(result, "__aiter__"):
            async for event in result:
                for chunk in encode(event):
                    yield chunk
        else:
            if not isinstance(result, dict):
                result = result.model_dump(mode="json", exclude_none=True)
            for event in response_events(result):
                for chunk in encode(event):
                    yield chunk
    finally:
        close = getattr(result, "aclose", None)
        if close is not None:
            await close()
