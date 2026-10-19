"""Incremental SSE framing with a strict per-frame memory bound."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from .protocol import CustomerChannelError


async def read_events(chunks: AsyncIterator[bytes], limit: int) -> AsyncIterator[dict]:
    """Handle split UTF-8, CRLF/CR/LF, comments and multiline SSE data.

    The byte limit includes comments/metadata and incomplete lines, preventing
    an unterminated or data-free frame from growing without bound.
    """
    line = bytearray()
    data: list[str] = []
    size = 0
    after_cr = False
    async for chunk in chunks:
        for byte in chunk:
            if after_cr and byte == 10:
                after_cr = False
                continue
            after_cr = False
            size += 1
            if size > limit:
                raise CustomerChannelError("event_too_large")
            if byte not in (10, 13):
                line.append(byte)
                continue
            after_cr = byte == 13
            try:
                text = line.decode("utf-8")
            except UnicodeError:
                raise CustomerChannelError("invalid_event") from None
            line.clear()
            if not text:
                size = 0
                if data:
                    try:
                        event = json.loads(
                            "\n".join(data), parse_constant=_invalid_constant
                        )
                    except (ValueError, RecursionError):
                        raise CustomerChannelError("invalid_event") from None
                    data.clear()
                    if not isinstance(event, dict):
                        raise CustomerChannelError("invalid_event")
                    yield event
            elif text == "data" or text.startswith("data:"):
                value = text.partition(":")[2]
                data.append(value[1:] if value.startswith(" ") else value)
    # SSE does not dispatch an unterminated final frame. The run owner rejects
    # EOF without a dispatched terminal, even if its bytes look like success.


def _invalid_constant(value: str):
    raise ValueError("Non-finite JSON value")
