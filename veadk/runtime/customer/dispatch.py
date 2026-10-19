"""Bounded reverse tool execution for one managed Shared channel."""

from __future__ import annotations

import asyncio
import copy
import inspect
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import anyio

from .client import CustomerChannelClient
from .protocol import CustomerChannelError, CustomerRunRequest

Executor = Callable[[dict[str, Any], str], Awaitable[Any]]


class _LocalToolFailure(CustomerChannelError):
    """A bridge failure must terminate the run instead of becoming tool output."""


@dataclass
class _ToolResult:
    content: Any
    status: str
    error: str


@dataclass
class _LocalToolEvents:
    request_id: str
    events: tuple
    accepted: asyncio.Future


class CustomerToolDispatcher:
    """Execute explicit async tools while continuing to receive cancellation.

    Use as an async context manager and consume ``events()`` once. Forwarded
    tool events are observations, not instructions to execute the tool again.
    The caller owns the client, trusted identity and durable session exclusion.
    A dispatcher owns exactly one run and cannot be restarted.
    """

    def __init__(
        self,
        client: CustomerChannelClient,
        request: CustomerRunRequest,
        executors: Mapping[str, Executor],
        *,
        max_concurrency: int = 8,
        event_queue_size: int = 16,
        cleanup_timeout: float = 10,
    ):
        for value, upper in ((max_concurrency, 64), (event_queue_size, 256)):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("Invalid dispatcher capacity")
        if (
            isinstance(cleanup_timeout, bool)
            or not isinstance(cleanup_timeout, (int, float))
            or not math.isfinite(cleanup_timeout)
            or cleanup_timeout <= 0
        ):
            raise ValueError("Invalid cleanup timeout")
        snapshot = CustomerRunRequest.model_validate(
            copy.deepcopy(request.model_dump())
        )
        functions = dict(executors)
        if set(functions) != {tool.name for tool in snapshot.tools}:
            raise ValueError("Executor catalog must match request tools")
        if any(
            not inspect.iscoroutinefunction(fn)
            and not inspect.iscoroutinefunction(getattr(fn, "__call__", None))
            for fn in functions.values()
        ):
            raise ValueError("Executors must be asynchronous")
        self._client = client
        self._request = snapshot
        self._executors = functions
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._queue: asyncio.Queue[dict | _LocalToolEvents] = asyncio.Queue(
            event_queue_size
        )
        self._cleanup_timeout = cleanup_timeout
        self._cleanup_deadline: float | None = None
        self._owner: asyncio.Task | None = None
        self._children: set[asyncio.Task] = set()
        self._jobs: dict[str, asyncio.Task] = {}
        self._cancelled: set[str] = set()
        self._cancel_requested: set[asyncio.Task] = set()
        self._failure: asyncio.Future | None = None
        self._active = False
        self._closed = False
        self._reading = False
        self._terminal: dict | None = None

    @property
    def quiescent(self) -> bool:
        """Whether every owned task has stopped, including late cleanup."""
        return (self._owner is None or self._owner.done()) and all(
            task.done() for task in self._children
        )

    async def __aenter__(self):
        if self._owner is not None or self._closed:
            raise CustomerChannelError("dispatcher_unavailable")
        self._active = True
        self._failure = asyncio.get_running_loop().create_future()
        self._owner = asyncio.create_task(self._run())
        self._owner.add_done_callback(self._retrieve)
        return self

    async def __aexit__(self, exc_type, *_):
        await self.aclose(raise_run_error=exc_type is None)

    @staticmethod
    def _retrieve(task):
        # Never log exception text; also consume exceptions after bounded exit.
        if not task.cancelled():
            task.exception()

    def _begin_cleanup(self):
        self._active = False
        if self._cleanup_deadline is None:
            self._cleanup_deadline = time.monotonic() + self._cleanup_timeout
        return max(0, self._cleanup_deadline - time.monotonic())

    async def aclose(self, *, raise_run_error: bool = True):
        """Revoke submissions before cancellation; bound the entire join."""
        self._begin_cleanup()
        if self._owner is None:
            self._closed = True
            return
        if not self._closed:
            self._closed = True
            if not self._owner.done():
                self._owner.cancel()
        with anyio.CancelScope(shield=True):
            waiting = {self._owner, *self._children}
            _, pending = await asyncio.wait(waiting, timeout=self._begin_cleanup())
        if pending or not self.quiescent:
            raise CustomerChannelError("cleanup_timeout")
        if raise_run_error and not self._owner.cancelled():
            error = self._owner.exception()
            if error is not None:
                raise error

    async def events(self) -> AsyncIterator[dict | _LocalToolEvents]:
        """Observe validated envelopes; success follows all result ACKs."""
        if self._owner is None or self._reading or self._closed:
            raise CustomerChannelError("dispatcher_unavailable")
        self._reading = True
        while True:
            if self._owner.done():
                if self._owner.cancelled():
                    raise CustomerChannelError("dispatcher_cancelled")
                self._owner.result()
                if self._queue.empty():
                    return
            receive = asyncio.create_task(self._queue.get())
            try:
                await asyncio.wait(
                    {receive, self._owner}, return_when=asyncio.FIRST_COMPLETED
                )
                if self._owner.done() and not self._owner.cancelled():
                    self._owner.result()
                if receive.done():
                    yield receive.result()
            finally:
                if not receive.done():
                    receive.cancel()
                await asyncio.gather(receive, return_exceptions=True)

    async def _emit(self, event):
        try:
            self._queue.put_nowait(copy.deepcopy(event))
        except asyncio.QueueFull:
            raise CustomerChannelError("event_backpressure") from None
        # Give a ready consumer a chance even for pre-buffered HTTP chunks.
        await asyncio.sleep(0)

    def _local_active(self, request_id):
        return self._active and request_id not in self._cancelled

    async def _emit_local(self, request_id, events):
        if not self._local_active(request_id):
            raise _LocalToolFailure("native_tool_closed")
        batch = _LocalToolEvents(
            request_id,
            copy.deepcopy(events),
            asyncio.get_running_loop().create_future(),
        )
        try:
            self._queue.put_nowait(batch)
        except asyncio.QueueFull:
            raise _LocalToolFailure("event_backpressure") from None
        await batch.accepted
        if not self._local_active(request_id):
            raise _LocalToolFailure("native_tool_closed")

    def _cancel_task(self, task):
        if not task.done() and task not in self._cancel_requested:
            self._cancel_requested.add(task)
            task.cancel()

    def _track(self, task, request_id=None):
        self._children.add(task)

        def finished(done):
            self._children.discard(done)
            self._cancel_requested.discard(done)
            if request_id is not None:
                self._jobs.pop(request_id, None)
            if done.cancelled():
                error = (
                    CustomerChannelError("executor_cancelled")
                    if self._active and request_id not in self._cancelled
                    else None
                )
            else:
                error = done.exception()
            if error is not None and self._active and not self._failure.done():
                self._failure.set_result(error)

        task.add_done_callback(finished)
        return task

    async def _read(self, channel):
        async for event in channel.events():
            kind = event["type"]
            if kind == "tool.call":
                # Cancelled tools may still be cleaning up; count those too.
                if len(self._jobs) >= 64:
                    raise CustomerChannelError("too_many_executors")
                request_id = event["request_id"]
                deadline = time.monotonic() + event["deadline_ms"] / 1000
                task = asyncio.create_task(self._execute(channel, event, deadline))
                self._jobs[request_id] = task
                self._track(task, request_id)
            elif kind == "tool.cancel":
                request_id = event["request_id"]
                self._cancelled.add(request_id)
                task = self._jobs.get(request_id)
                if task is not None:
                    self._cancel_task(task)
            elif kind == "run.completed":
                self._terminal = event
                return
            await self._emit(event)

    async def _execute(self, channel, event, deadline):
        request_id = event["request_id"]
        try:
            with anyio.fail_after(max(0, deadline - time.monotonic())):
                async with self._semaphore:
                    if not self._active or request_id in self._cancelled:
                        return
                    try:
                        result = await self._executors[event["tool_name"]](
                            copy.deepcopy(event["arguments"]), request_id
                        )
                        status, error = "success", ""
                        if isinstance(result, _ToolResult):
                            result, status, error = (
                                result.content,
                                result.status,
                                result.error,
                            )
                    except asyncio.CancelledError:
                        raise
                    except _LocalToolFailure:
                        raise
                    except Exception:
                        result, status, error = None, "error", "tool_execution_failed"
                    if not self._active or request_id in self._cancelled:
                        return
                    if time.monotonic() >= deadline:
                        raise CustomerChannelError("tool_timeout")
                    await channel.submit_result(
                        request_id, content=result, status=status, error=error
                    )
        except TimeoutError:
            raise CustomerChannelError("tool_timeout") from None

    async def _run(self):
        try:
            async with self._client.run(self._request) as channel:
                try:
                    reader = self._track(asyncio.create_task(self._read(channel)))
                    await asyncio.wait(
                        {reader, self._failure}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if self._failure.done():
                        raise self._failure.result()
                    await reader
                    while self._jobs:
                        await asyncio.wait(
                            {*self._jobs.values(), self._failure},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if self._failure.done():
                            raise self._failure.result()
                    if self._failure.done():
                        raise self._failure.result()
                    if self._terminal is None:
                        raise CustomerChannelError("incomplete_stream")
                    await self._emit(self._terminal)
                finally:
                    self._begin_cleanup()
                    tasks = set(self._children)
                    for task in tasks:
                        self._cancel_task(task)
                    if tasks:
                        with anyio.CancelScope(shield=True):
                            _, pending = await asyncio.wait(
                                tasks,
                                timeout=min(
                                    self._cleanup_timeout / 2, self._begin_cleanup()
                                ),
                            )
                        if pending:
                            raise CustomerChannelError("cleanup_timeout")
        finally:
            self._active = False
