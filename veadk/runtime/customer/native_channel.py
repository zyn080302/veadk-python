"""Adapt native deferred-tool HTTP steps to the existing customer dispatcher."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from contextlib import asynccontextmanager

import anyio
import httpx
from jsonschema import Draft202012Validator

from .cleanup import _run_cleanup
from .client import _encode
from .protocol import CustomerChannelError
from .messages import validate_user_message
from .sse import read_events


def _native_payload(request, message):
    def invalid_constant(_):
        raise ValueError

    try:
        config = json.loads(
            request.agent_config.get_secret_value(), parse_constant=invalid_constant
        )
        if not isinstance(config, dict) or not config or request.environment:
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise CustomerChannelError("invalid_native_configuration") from None
    run_config = {"skills": [s.model_dump(mode="json") for s in request.skills]}
    if request.thinking is not None:
        run_config["thinking"] = request.thinking
    return {
        "appName": request.app_name,
        "userId": request.user_id,
        "sessionId": request.session_id,
        "newMessage": message,
        "streaming": True,
        "harness_config": {
            "agent_config": config,
            "studio_tools": [
                t.model_dump(mode="json", exclude={"source"}, exclude_none=True)
                for t in request.tools
            ],
            "run_config": run_config,
        },
    }


@asynccontextmanager
async def _native_run(client, request):
    # Validate and size-check before submitting any remote effect.
    message = validate_user_message(request.new_message, attachments=True)
    request = request.model_copy(update={"new_message": message})
    _encode(_native_payload(request, message), client._initial_request_limit)
    channel = _NativeChannel(client, request)
    client._active = True
    try:
        with anyio.fail_after(client._turn_timeout) as deadline:
            yield channel
    except TimeoutError:
        if not deadline.cancel_called:
            raise
        raise CustomerChannelError("run_timeout") from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise CustomerChannelError("transport_error") from None
    finally:
        channel._closed = True
        try:
            await channel.close_response()
        finally:
            for _, future in channel._submitted.values():
                future.cancel()
            channel._submitted.clear()
            channel._pending.clear()
            channel._expected = None
            client._active = False


class _NativeChannel:
    def __init__(self, client, request):
        # Lazy import avoids a client -> events -> dispatch -> client cycle.
        from .events import _Projector

        self._client = client
        self._request = request
        self._tools = {t.name: t for t in request.tools}
        self._schemas = {
            t.name: Draft202012Validator(t.input_schema) for t in request.tools
        }
        self._catalog_revision = request.catalog_revision
        self._validator = _Projector(
            author="native_validator",
            invocation_id=request.run_id,
            new_message=request.new_message,
            branch=None,
            attachments=True,
        )
        self._response = None
        self._closed = False
        self._reading = False
        self._terminal = False
        self._pending = {}
        self._submitted = {}
        self._staged_bytes = 0
        self._results_ready = asyncio.Event()
        self._expected = None

    async def close_response(self):
        response, self._response = self._response, None
        if response is not None:
            try:
                await _run_cleanup(
                    response.aclose(), timeout=self._client._cleanup_timeout
                )
            except TimeoutError:
                raise CustomerChannelError("cleanup_timeout") from None

    def _check_submissions(self):
        if any(
            time.monotonic() >= deadline for _, deadline in self._pending.values()
        ) or any(future.cancelled() for _, future in self._submitted.values()):
            raise CustomerChannelError("stale_tool_result")

    async def _step(self, message, *, initial):
        client = self._client
        content = _encode(
            _native_payload(self._request, message),
            client._initial_request_limit if initial else client._request_limit,
        )
        try:
            req = client._http.build_request(
                "POST",
                client._endpoint + "/run_sse",
                headers=await client._request_headers(),
                content=content,
            )
            if self._expected is not None:
                self._check_submissions()
            try:
                with anyio.fail_after(client._operation_timeout):
                    self._response = await client._http.send(req, stream=True)
            except TimeoutError:
                raise CustomerChannelError("operation_timeout") from None
            await client._check_response(self._response)
            if (
                self._response.headers.get("content-type", "").split(";")[0].strip()
                != "text/event-stream"
            ):
                raise CustomerChannelError("invalid_content_type")
            async for raw in read_events(
                self._response.aiter_bytes(), client._event_limit
            ):
                yield raw
        finally:
            await self.close_response()

    def _normalize(self, raw):
        from .events import _field

        value = copy.deepcopy(raw)
        is_echo = self._expected is not None
        if is_echo:
            try:
                content_matches = json.dumps(
                    raw.get("content"), sort_keys=True, allow_nan=False
                ) == json.dumps(self._expected, sort_keys=True, allow_nan=False)
            except (TypeError, ValueError, RecursionError):
                raise CustomerChannelError("result_not_accepted") from None
            if raw.get("author") != "user" or not content_matches:
                raise CustomerChannelError("result_not_accepted")
            if raw.get("partial", False) is not False:
                raise CustomerChannelError("result_not_accepted")
            value["author"] = "native_result_echo"
        elif raw.get("author") == "user" and self._validator.count:
            raise CustomerChannelError("unexpected_user_event")
        long_ids = _field(raw, "longRunningToolIds", "long_running_tool_ids")
        if long_ids is None:
            long_ids = []
        if not isinstance(long_ids, list) or any(
            not isinstance(i, str) for i in long_ids
        ):
            raise CustomerChannelError("invalid_tool_call")
        if len(long_ids) != len(set(long_ids)):
            raise CustomerChannelError("invalid_tool_call")
        content = raw.get("content")
        parts = content.get("parts", []) if isinstance(content, dict) else []
        local = []
        if isinstance(parts, list):
            for part in parts:
                call = (
                    _field(part, "functionCall", "function_call")
                    if isinstance(part, dict)
                    else None
                )
                if not isinstance(call, dict):
                    continue
                name = call.get("name")
                declaration = self._tools.get(name) if isinstance(name, str) else None
                if declaration is None:
                    continue
                try:
                    self._schemas[name].validate(call.get("args"))
                except Exception:
                    raise CustomerChannelError("invalid_tool_arguments") from None
                local.append((call, declaration))
        ids = [c.get("id") for c, _ in local]
        if any(not isinstance(i, str) for i in ids) or set(long_ids) != set(ids):
            raise CustomerChannelError("invalid_tool_call")
        if long_ids and raw.get("partial", False):
            raise CustomerChannelError("unsupported_partial_tool_event")
        if self._pending and len(self._pending) + len(local) > 64:
            raise CustomerChannelError("too_many_tool_calls")
        value.pop("longRunningToolIds", None)
        value.pop("long_running_tool_ids", None)
        # This validates IDs, aliases, complete content, interaction and final order
        # before any executable call or real result ACK becomes observable.
        self._validator.project(value)
        if is_echo:
            if any(
                time.monotonic() >= deadline for _, deadline in self._pending.values()
            ):
                raise CustomerChannelError("stale_tool_result")
            for _, future in self._submitted.values():
                if future.cancelled():
                    raise CustomerChannelError("stale_tool_result")
            for _, future in self._submitted.values():
                future.set_result(None)
            self._submitted.clear()
            self._pending.clear()
            self._expected = None
            self._staged_bytes = 0
            self._results_ready.clear()
        calls = []
        if local:
            self._results_ready.clear()
        for call, declaration in local:
            self._pending[call["id"]] = (
                declaration.name,
                time.monotonic() + declaration.timeout_ms / 1000,
            )
            calls.append(
                {
                    "type": "tool.call",
                    "run_id": self._request.run_id,
                    "request_id": call["id"],
                    "tool_name": declaration.name,
                    "arguments": copy.deepcopy(call["args"]),
                    "deadline_ms": declaration.timeout_ms,
                    "executor_revision": declaration.executor_revision,
                    "scope_id": self._request.scope_id,
                    "catalog_revision": self._catalog_revision,
                }
            )
        return value, calls

    async def events(self):
        from contextlib import aclosing

        if self._closed or self._reading:
            raise CustomerChannelError("stream_unavailable")
        self._reading = True
        message = self._request.new_message
        initial = True
        while True:
            async with aclosing(self._step(message, initial=initial)) as events:
                async for raw in events:
                    normalized, calls = self._normalize(raw)
                    yield {
                        "type": "run.event",
                        "run_id": self._request.run_id,
                        "event": normalized,
                    }
                    for call in calls:
                        yield call
            if self._expected is not None:
                raise CustomerChannelError("result_not_accepted")
            if not self._pending:
                self._validator.finish()
                self._terminal = True
                yield {
                    "type": "run.completed",
                    "run_id": self._request.run_id,
                    "status": "success",
                }
                return
            await self._results_ready.wait()
            if self._closed:
                raise CustomerChannelError("stream_unavailable")
            self._check_submissions()
            message = {
                "role": "user",
                "parts": [
                    {"functionResponse": self._submitted[i][0]} for i in self._pending
                ],
            }
            # The complete batch (including config) must fit before next HTTP.
            _encode(
                _native_payload(self._request, message), self._client._request_limit
            )
            self._expected = copy.deepcopy(message)
            initial = False

    async def submit_result(
        self, request_id, *, content=None, status="success", error=""
    ):
        if (
            self._closed
            or self._terminal
            or not isinstance(request_id, str)
            or request_id not in self._pending
            or request_id in self._submitted
        ):
            raise CustomerChannelError("stale_tool_result")
        if status not in ("success", "error", "denied", "timeout") or not isinstance(
            error, str
        ):
            raise CustomerChannelError("invalid_tool_result")
        name, deadline = self._pending[request_id]
        if time.monotonic() >= deadline:
            raise CustomerChannelError("stale_tool_result")
        if status == "success":
            payload = content if isinstance(content, dict) else {"result": content}
        else:
            payload = {
                "error": "tool_execution_failed" if status == "error" else status
            }
        response = {"id": request_id, "name": name, "response": payload}
        encoded = _encode(response, self._client._request_limit)
        if self._staged_bytes + len(encoded) > self._client._request_limit:
            raise CustomerChannelError("request_too_large")
        future = asyncio.get_running_loop().create_future()
        self._submitted[request_id] = (json.loads(encoded), future)
        self._staged_bytes += len(encoded)
        if len(self._submitted) == len(self._pending):
            self._results_ready.set()
        # Consumed even if cancelled or delivery is ambiguous. No replay.
        await future
