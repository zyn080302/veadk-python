"""Bounded cleanup joins that defer repeated caller cancellation."""

from __future__ import annotations

import asyncio

import anyio


async def _wait_cleanup(tasks, *, timeout):
    """Join existing tasks without forwarding cancellation or resetting time."""
    owned = set(tasks)
    pending = owned.copy()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    cancelled = None
    with anyio.CancelScope(shield=True):
        while pending:
            remaining = max(0, deadline - loop.time())
            try:
                _, pending = await asyncio.wait(pending, timeout=remaining)
            except asyncio.CancelledError as error:
                # AnyIO shielding does not block direct Task.cancel(). asyncio.wait
                # leaves the owned tasks intact, unlike awaiting them directly.
                cancelled = error
                pending = {task for task in pending if not task.done()}
            if loop.time() >= deadline:
                break
    if cancelled is not None:
        raise cancelled
    return owned - pending, pending


def _retrieve(task):
    if not task.cancelled():
        task.exception()


async def _run_cleanup(operation, *, timeout):
    """Own a leaf cleanup operation; never migrate an open generator or scope."""
    task = asyncio.create_task(operation)
    task.add_done_callback(_retrieve)
    try:
        _, pending = await _wait_cleanup({task}, timeout=timeout)
        if pending:
            raise TimeoutError
        return task.result()
    finally:
        if not task.done():
            # Bound the caller even if third-party code ignores cancellation.
            task.cancel()
