"""Project Shared events without importing remote identity or executable state."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import aclosing
from uuid import uuid4

from .dispatch import CustomerToolDispatcher
from .protocol import CustomerChannelError


def _field(data, camel, snake):
    if camel in data and snake in data:
        raise CustomerChannelError("invalid_adk_event")
    return data.get(camel, data.get(snake))


def _identifier(value, limit):
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
    )


def _json_size(data):
    try:
        size = len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())
    except (TypeError, ValueError, RecursionError):
        raise CustomerChannelError("invalid_adk_event") from None
    if size > 1024 * 1024:
        raise CustomerChannelError("adk_event_too_large")


class _Projector:
    def __init__(self, *, author, invocation_id, new_message, branch):
        if (
            not _identifier(author, 128)
            or author == "user"
            or not _identifier(invocation_id, 256)
            or (branch is not None and not _identifier(branch, 256))
        ):
            raise ValueError("Invalid local event identity")
        try:
            _json_size(new_message)
            if (
                not isinstance(new_message, dict)
                or set(new_message) != {"role", "parts"}
                or new_message["role"] != "user"
                or not isinstance(new_message["parts"], list)
                or not new_message["parts"]
                or not all(
                    isinstance(p, dict)
                    and set(p) == {"text"}
                    and isinstance(p["text"], str)
                    for p in new_message["parts"]
                )
                or not any(p["text"] for p in new_message["parts"])
            ):
                raise ValueError
        except (ValueError, CustomerChannelError):
            raise ValueError("Expected a nonempty text user message") from None
        self.message = copy.deepcopy(new_message)
        self.identity = dict(author=author, invocation_id=invocation_id, branch=branch)
        self.count = 0
        self.seen = set()
        self.calls = {}
        self.pending = set()
        self.final = None

    def project(self, raw):
        from google.adk.events import Event
        from google.genai import types

        self.count += 1
        if self.count > 4096:
            raise CustomerChannelError("too_many_adk_events")
        _json_size(raw)
        if not isinstance(raw, dict):
            raise CustomerChannelError("invalid_adk_event")
        if any(
            raw.get(k)
            for k in (
                "error",
                "errorCode",
                "error_code",
                "errorMessage",
                "error_message",
            )
        ):
            raise CustomerChannelError("remote_event_error")
        if raw.get("interrupted"):
            raise CustomerChannelError("remote_event_interrupted")
        partial = raw.get("partial", False)
        if type(partial) is not bool:
            raise CustomerChannelError("invalid_adk_event")
        event_id = raw.get("id")
        if not _identifier(event_id, 128):
            raise CustomerChannelError("invalid_adk_event")
        if not partial:
            if event_id in self.seen:
                raise CustomerChannelError("duplicate_adk_event")
            self.seen.add(event_id)
        content = raw.get("content")
        if raw.get("author") == "user":
            if self.count != 1 or partial or content != self.message:
                raise CustomerChannelError("unexpected_user_event")
            return None
        self._check_interactive(raw)
        parts, role = self._content(content, partial)
        usage = self._usage(raw) if not partial else None
        if self.final is not None and content is not None:
            is_final = not partial and not any(
                p.function_call or p.function_response for p in parts
            )
            raise CustomerChannelError(
                "multiple_final_responses" if is_final else "event_after_final"
            )
        if not parts and usage is None and content is None:
            return None
        event = Event(
            **self.identity,
            content=types.Content(role=role, parts=parts)
            if content is not None
            else None,
            usage_metadata=usage,
            partial=partial,
        )
        has_tools = any(p.function_call or p.function_response for p in parts)
        has_answer = any(p.text is not None and not p.thought for p in parts)
        turn_complete = _field(raw, "turnComplete", "turn_complete")
        if turn_complete is not None and type(turn_complete) is not bool:
            raise CustomerChannelError("invalid_adk_event")
        empty_answer = content is not None and not parts and turn_complete is True
        if not partial and not has_tools and (has_answer or empty_answer):
            self.final = event
            return None
        if not has_tools:
            # ADK otherwise considers contentless and pure-thought Events final.
            event.partial = True
        return event

    @staticmethod
    def _check_interactive(raw):
        actions = raw.get("actions") or {}
        if not isinstance(actions, dict):
            raise CustomerChannelError("invalid_adk_event")
        if _field(raw, "longRunningToolIds", "long_running_tool_ids") or any(
            actions.get(k)
            for k in (
                "requestedAuthConfigs",
                "requested_auth_configs",
                "requestedToolConfirmations",
                "requested_tool_confirmations",
            )
        ):
            raise CustomerChannelError("unsupported_interactive_event")

    def _content(self, content, partial):
        from google.genai import types

        if content is None:
            return [], "model"
        if (
            not isinstance(content, dict)
            or set(content) - {"role", "parts"}
            or not isinstance(content.get("role"), str)
            or content.get("role") not in {"user", "model"}
            or not isinstance(content.get("parts"), list)
            or (content["role"] == "user" and not content["parts"])
        ):
            raise CustomerChannelError("invalid_adk_event")
        parts = []
        for raw in content["parts"]:
            if not isinstance(raw, dict):
                raise CustomerChannelError("invalid_adk_event")
            raw = {k: v for k, v in raw.items() if v is not None}
            if set(raw) - {
                "text",
                "thought",
                "thoughtSignature",
                "thought_signature",
                "functionCall",
                "function_call",
                "functionResponse",
                "function_response",
            }:
                raise CustomerChannelError("unsupported_adk_content")
            call = _field(raw, "functionCall", "function_call")
            response = _field(raw, "functionResponse", "function_response")
            if sum(("text" in raw, call is not None, response is not None)) != 1:
                raise CustomerChannelError("unsupported_adk_content")
            if "text" in raw:
                if (
                    content["role"] != "model"
                    or not isinstance(raw["text"], str)
                    or type(raw.get("thought", False)) is not bool
                ):
                    raise CustomerChannelError("invalid_adk_event")
                parts.append(types.Part(text=raw["text"], thought=raw.get("thought")))
            else:
                if partial:
                    raise CustomerChannelError("unsupported_partial_tool_event")
                if call is not None and content["role"] != "model":
                    raise CustomerChannelError("invalid_display_tool_call")
                parts.append(
                    self._tool(call if call is not None else response, call is not None)
                )
        return parts, content["role"]

    def _tool(self, raw, is_call):
        from google.genai import types

        code = (
            "invalid_display_tool_call" if is_call else "invalid_display_tool_response"
        )
        data_key = "args" if is_call else "response"
        if (
            not isinstance(raw, dict)
            or set(raw) - {"id", "name", data_key}
            or not _identifier(raw.get("id"), 128)
            or not _identifier(raw.get("name"), 64)
            or not isinstance(raw.get(data_key), dict)
        ):
            raise CustomerChannelError(code)
        remote_id, name = raw["id"], raw["name"]
        if is_call:
            if (
                remote_id in self.calls
                or len(self.calls) >= 1024
                or len(self.pending) >= 64
            ):
                raise CustomerChannelError(code)
            self.calls[remote_id] = (name, uuid4().hex)
            self.pending.add(remote_id)
        else:
            if remote_id not in self.pending or self.calls[remote_id][0] != name:
                raise CustomerChannelError(code)
            self.pending.remove(remote_id)
        value = {
            "name": name,
            "id": self.calls[remote_id][1],
            data_key: copy.deepcopy(raw[data_key]),
        }
        try:
            if is_call:
                return types.Part(function_call=types.FunctionCall(**value))
            return types.Part(function_response=types.FunctionResponse(**value))
        except ValueError:
            raise CustomerChannelError(code) from None

    @staticmethod
    def _usage(raw):
        from google.genai import types

        usage = _field(raw, "usageMetadata", "usage_metadata")
        if usage is None:
            return None
        if not isinstance(usage, dict):
            raise CustomerChannelError("invalid_adk_event")
        result = {}
        for camel, snake in (
            ("promptTokenCount", "prompt_token_count"),
            ("candidatesTokenCount", "candidates_token_count"),
            ("totalTokenCount", "total_token_count"),
            ("cachedContentTokenCount", "cached_content_token_count"),
            ("thoughtsTokenCount", "thoughts_token_count"),
        ):
            value = _field(usage, camel, snake)
            if value is not None:
                if type(value) is not int or not 0 <= value <= 2**53 - 1:
                    raise CustomerChannelError("invalid_adk_event")
                result[snake] = value
        return types.GenerateContentResponseUsageMetadata(**result) if result else None

    def finish(self):
        if self.pending:
            raise CustomerChannelError("unresolved_display_tools")
        if self.final is None:
            raise CustomerChannelError("missing_final_response")
        final, self.final = self.final, None
        final.turn_complete = True
        return final


class CustomerAdkEventStream:
    """One dispatcher run projected to local ADK display events.

    Use ``async with`` and consume ``events()`` in the same task. The caller
    owns durable session exclusion and persistence, and must never replay a
    failed invocation or execute observed function calls a second time.
    """

    def __init__(
        self,
        dispatcher: CustomerToolDispatcher,
        *,
        author: str,
        invocation_id: str,
        new_message: dict,
        branch: str | None = None,
    ):
        self._projector = _Projector(
            author=author,
            invocation_id=invocation_id,
            new_message=new_message,
            branch=branch,
        )
        self._dispatcher = dispatcher
        self._owner = None
        self._iterator = None
        self._closed = False

    async def __aenter__(self):
        if self._owner is not None or self._closed:
            raise CustomerChannelError("event_stream_unavailable")
        self._owner = asyncio.current_task()
        try:
            await self._dispatcher.__aenter__()
        except BaseException:
            self._closed = True
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if asyncio.current_task() is not self._owner:
            raise CustomerChannelError("event_stream_task_mismatch")
        self._closed = True
        try:
            if self._iterator is not None:
                await self._iterator.aclose()
        finally:
            self._projector.final = None
            await self._dispatcher.__aexit__(exc_type, exc, tb)

    def events(self):
        if self._closed or self._owner is None or self._iterator is not None:
            raise CustomerChannelError("event_stream_unavailable")
        if asyncio.current_task() is not self._owner:
            raise CustomerChannelError("event_stream_task_mismatch")
        self._iterator = self._events()
        return self._iterator

    async def _events(self):
        success = False
        async with aclosing(self._dispatcher.events()) as envelopes:
            async for envelope in envelopes:
                if asyncio.current_task() is not self._owner:
                    raise CustomerChannelError("event_stream_task_mismatch")
                if envelope["type"] == "run.event":
                    event = self._projector.project(envelope["event"])
                    if event is not None:
                        yield event
                elif envelope["type"] == "run.completed":
                    success = envelope.get("status") == "success"
        if not success:
            raise CustomerChannelError("incomplete_stream")
        final = self._projector.finish()
        await self._dispatcher.aclose()
        yield final
