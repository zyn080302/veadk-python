"""Bounded live Responses delivery across shim-owned tool rounds.

The shim owns ADK calls; Codex owns native calls. Never expose an ADK call as
an executable SSE item. Text can flow immediately, while item completion waits
for the round outcome so exploratory preambles can be marked commentary.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any


class TurnResponseError(RuntimeError):
    def __init__(self, *, status_code, error_type, message, template=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.template = template or {}


def _dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    return value.model_dump(mode="json", exclude_none=True)


class ResponsesStream:
    """One downstream response, with backpressure and cancellation ownership."""

    def __init__(
        self,
        *,
        model,
        executors,
        synthesize,
        record_error,
        fatal_code,
        retryable_error=lambda _exc: False,
    ):
        self.model = model
        self.executors = set(executors)
        self.synthesize = synthesize
        self.record_error = record_error
        self.fatal_code = fatal_code
        self.retryable_error = retryable_error
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self.sequence = 0
        self.started = False
        self.prefix = uuid.uuid4().hex
        self.template: dict[str, Any] = {
            "id": "resp_veadk_" + self.prefix,
            "model": model,
        }
        self.items: list[dict] = []
        self.visible: dict[int, int] = {}

    async def _emit(self, event):
        event = {**event, "sequence_number": self.sequence}
        self.sequence += 1
        await self.queue.put(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
        )

    async def _start(self, response=None):
        if self.started:
            return
        self.started = True
        if response:
            # Lifecycle metadata only; never echo request instructions/tools.
            self.template.update(
                {
                    k: response[k]
                    for k in ("id", "object", "model", "created_at")
                    if k in response
                }
            )
        progress = {**self.template, "status": "in_progress", "output": []}
        await self._emit({"type": "response.created", "response": progress})
        await self._emit({"type": "response.in_progress", "response": progress})

    async def _item_event(self, event):
        idx = event.get("output_index")
        kind = event["type"]
        if kind == "response.output_item.added":
            if idx in self.visible:
                raise RuntimeError("Duplicate streaming output index")
            self.visible[idx] = len(self.items)
            self.items.append({})
        if idx not in self.visible:
            return
        mapped = self.visible[idx]
        item_id = f"veadk_{self.prefix}_item_{mapped}"
        event = {**event, "output_index": mapped}
        if "item_id" in event:
            event["item_id"] = item_id
        if "item" in event:
            event["item"] = {**event["item"], "id": item_id}
            self.items[mapped] = event["item"]
        await self._start()
        await self._emit(event)

    async def collect(self, result: Any) -> dict:
        """Consume one backend stream, returning its complete tool-loop input.

        Completed-only bridges are supported without pretending their response
        is live. A missing terminal event is an error, never an empty success.
        """
        self.visible = {}
        if not hasattr(result, "__aiter__"):
            return _dict(result)
        done: dict[int, dict] = {}
        deltas: dict[tuple[int, int], str] = {}
        terminal = None
        try:
            async for raw in result:
                event = _dict(raw)
                kind = event.get("type", "")
                if kind == "error":
                    raise RuntimeError("Backend response stream failed or incomplete")
                if kind in (
                    "response.completed",
                    "response.failed",
                    "response.incomplete",
                ):
                    terminal = event.get("response")
                    expected_status = kind.removeprefix("response.")
                    if (
                        not isinstance(terminal, dict)
                        or terminal.get("status") not in (None, expected_status)
                        or not isinstance(terminal.get("output"), list)
                    ):
                        raise RuntimeError("Backend response has an invalid terminal")
                    terminal = {**terminal, "status": expected_status}
                    break
                if kind in ("response.created", "response.in_progress"):
                    await self._start(event.get("response"))
                    continue
                idx = event.get("output_index")
                if kind == "response.output_item.added":
                    if event.get("item", {}).get("type") in ("message", "reasoning"):
                        await self._item_event(event)
                elif idx in self.visible:
                    if kind == "response.output_item.done":
                        done[idx] = event
                    else:
                        if kind == "response.output_text.delta":
                            key = (idx, event.get("content_index", 0))
                            deltas[key] = deltas.get(key, "") + event.get("delta", "")
                        await self._item_event(event)
            if terminal is None:
                raise RuntimeError("Backend stream ended before response.completed")
            output = terminal.get("output") or []
            local_calls = terminal["status"] == "completed" and any(
                i.get("type") == "function_call" and i.get("name") in self.executors
                for i in output
            )
            for idx in self.visible:
                if idx not in done or not isinstance(idx, int) or idx >= len(output):
                    raise RuntimeError("Backend stream has an unfinished item")
                item = done[idx]["item"]
                if item.get("type") != output[idx].get("type") or item.get(
                    "id"
                ) != output[idx].get("id"):
                    raise RuntimeError(
                        "Backend completed output differs from streamed items"
                    )
                if item.get("type") == "message":
                    for cidx, part in enumerate(item.get("content") or []):
                        if part.get("type") == "output_text":
                            if deltas.get((idx, cidx), "") != part.get("text", ""):
                                raise RuntimeError(
                                    "Backend completed text differs from streamed text"
                                )
                    if item.get("content") != output[idx].get("content"):
                        raise RuntimeError("Backend completed output changed text")
                    if local_calls:
                        item = {**item, "phase": "commentary"}
                await self._item_event({**done[idx], "item": item})
            return terminal
        finally:
            # LiteLLM's Responses iterator has no aclose; its httpx response
            # owns the socket. Async generators/SDK streams expose aclose.
            close = getattr(result, "aclose", None)
            if close is None:
                close = getattr(getattr(result, "response", None), "aclose", None)
            if close is not None:
                await close()

    async def _finish(self, response):
        status = response.get("status") or "completed"
        if status not in ("completed", "failed", "incomplete"):
            raise RuntimeError("Backend response has an invalid status")
        # Buffered bridges and native tools still need canonical item events.
        missing = [
            i
            for idx, i in enumerate(response.get("output") or [])
            if idx not in self.visible
            and (status == "completed" or i.get("type") != "function_call")
        ]
        self.visible = {}
        async for raw in self.synthesize({**response, "output": missing}):
            event = json.loads(raw.decode().split("data: ", 1)[1])
            if "output_index" in event:
                await self._item_event(event)
        await self._start(response)
        completed = {
            **response,
            **self.template,
            "status": status,
            "output": self.items,
        }
        await self._emit({"type": f"response.{status}", "response": completed})

    async def run(
        self, operation: Callable[[], Awaitable[dict]]
    ) -> AsyncIterator[bytes]:
        async def produce():
            try:
                await self._finish(await operation())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.record_error(exc)
                await self._start()
                # No raw provider exception or request payload on the wire.
                message = f"Response generation failed: {type(exc).__name__}"
                template = self.template
                if isinstance(exc, TurnResponseError):
                    message = f"{exc.error_type}: {exc}"
                    template = {**template, **exc.template}
                await self._emit(
                    {
                        "type": "response.failed",
                        "response": {
                            **template,
                            "status": "failed",
                            "output": self.items,
                            "error": {
                                "code": "server_error"
                                if self.retryable_error(exc)
                                else self.fatal_code,
                                "message": message,
                            },
                        },
                    }
                )

        worker = asyncio.create_task(produce())
        pending = None
        try:
            while not worker.done() or not self.queue.empty():
                if not self.queue.empty():
                    yield self.queue.get_nowait()
                    continue
                pending = asyncio.create_task(self.queue.get())
                done, _ = await asyncio.wait(
                    (pending, worker), return_when=asyncio.FIRST_COMPLETED
                )
                if pending in done:
                    yield pending.result()
                else:
                    pending.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pending
                pending = None
            await worker
        finally:
            if pending is not None:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
            if not worker.done():
                worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
