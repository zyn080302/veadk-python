"""Session-owned managed customer HTTP channel with bounded cleanup."""

from __future__ import annotations

import asyncio
import copy
import json
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import quote, urlsplit

import anyio
import httpx
from jsonschema import Draft202012Validator
from pydantic import SecretStr

from .protocol import CHANNEL_PATH, PROTOCOL, CustomerChannelError, CustomerRunRequest
from .sse import read_events


def _encode(body, limit):
    try:
        encoded = json.dumps(
            body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    except (TypeError, ValueError, RecursionError):
        raise CustomerChannelError("invalid_request") from None
    if len(encoded) > limit:
        raise CustomerChannelError("request_too_large")
    return encoded


def _validate_endpoint(endpoint):
    if not isinstance(endpoint, str):
        raise ValueError("Invalid customer endpoint")
    try:
        parsed = urlsplit(endpoint)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and (
                parsed.scheme == "https"
                or parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            )
        )
        valid = valid and not any(ord(c) <= 32 for c in endpoint)
        # Force port validation here instead of leaking InvalidURL later.
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Invalid customer endpoint") from None


class CustomerChannelClient:
    """One HTTP pool and private affinity value per trusted business session.

    Use as an async context manager. Header providers and the endpoint are
    server-owned; never forward browser headers wholesale. Injected transports
    are caller-owned test infrastructure and must not add automatic retries.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        headers: Callable[[], Mapping[str, str]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        on_affinity: Callable[[SecretStr], Awaitable[None]] | None = None,
        operation_timeout: float = 30,
        turn_timeout: float = 165,
        cleanup_timeout: float = 5,
        max_event_bytes: int = 1024 * 1024,
        max_request_bytes: int = 2 * 1024 * 1024,
    ):
        _validate_endpoint(endpoint)
        for value in (operation_timeout, turn_timeout, cleanup_timeout):
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("Timeouts must be positive finite numbers")
        for value in (max_event_bytes, max_request_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("Byte limits must be positive integers")
        self._endpoint = endpoint.rstrip("/")
        self._headers_provider = headers
        self._affinity: str | None = None
        self._on_affinity = on_affinity
        self._affinity_lock = asyncio.Lock()
        self._affinity_failed = False
        self._identity: tuple[str, str, str] | None = None
        self._active = False
        self._control_active = False
        self._closed = False
        self._operation_timeout = operation_timeout
        self._turn_timeout = turn_timeout
        self._cleanup_timeout = cleanup_timeout
        self._event_limit = max_event_bytes
        self._request_limit = max_request_bytes
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=operation_timeout,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )

    async def __aenter__(self):
        if self._closed:
            raise CustomerChannelError("client_closed")
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self):
        self._closed = True
        try:
            with anyio.move_on_after(self._cleanup_timeout, shield=True):
                await self._http.aclose()
        finally:
            self._affinity = None
            self._headers_provider = None
            self._on_affinity = None

    async def _request_headers(self):
        async with self._affinity_lock:
            return self._headers()

    def _headers(self):
        if self._closed:
            raise CustomerChannelError("client_closed")
        if self._affinity_failed:
            raise CustomerChannelError("affinity_persistence_failed")
        try:
            headers = httpx.Headers(
                self._headers_provider() if self._headers_provider else {}
            )
            # Affinity is a private response value, never a caller's identity.
            headers.pop("X-Session-Id", None)
            if self._affinity:
                headers["X-Session-Id"] = self._affinity
            headers["Content-Type"] = "application/json"
            headers["Accept"] = "application/json, text/event-stream"
            return headers
        except Exception:
            raise CustomerChannelError("invalid_headers") from None

    def restore_session(self, app_name, user_id, session_id, *, affinity=None):
        """Restore a trusted binding once, before any HTTP operation."""
        if (
            self._closed
            or self._identity is not None
            or self._active
            or self._control_active
        ):
            raise CustomerChannelError("client_busy")
        self._validate_identity(app_name, user_id, session_id)
        if affinity is not None:
            if not isinstance(affinity, SecretStr):
                raise ValueError("Private affinity requires SecretStr")
            self._validate_affinity(affinity.get_secret_value())
        self._bind((app_name, user_id, session_id))
        self._affinity = affinity.get_secret_value() if affinity is not None else None

    @staticmethod
    def _validate_affinity(affinity):
        if (
            not affinity
            or len(affinity) > 8192
            or any(ord(c) < 32 or ord(c) == 127 for c in affinity)
        ):
            raise CustomerChannelError("invalid_affinity")

    async def _check_response(self, response):
        if not 200 <= response.status_code < 300:
            raise CustomerChannelError(f"http_status_{response.status_code}")
        affinity = response.headers.get("X-Session-Id")
        if affinity is not None:
            self._validate_affinity(affinity)
            async with self._affinity_lock:
                if self._affinity_failed:
                    raise CustomerChannelError("affinity_persistence_failed")
                if affinity != self._affinity:
                    try:
                        if self._on_affinity is not None:
                            await self._on_affinity(SecretStr(affinity))
                    except BaseException as error:
                        self._affinity_failed = True
                        if isinstance(error, Exception):
                            raise CustomerChannelError(
                                "affinity_persistence_failed"
                            ) from None
                        raise
                    self._affinity = affinity

    def _bind(self, identity):
        if self._identity is not None and self._identity != identity:
            raise CustomerChannelError("session_mismatch")
        self._identity = identity

    async def _json(self, method, path, body=None):
        content = None if body is None else _encode(body, self._request_limit)
        try:
            with anyio.fail_after(self._operation_timeout):
                async with self._http.stream(
                    method,
                    self._endpoint + path,
                    headers=await self._request_headers(),
                    content=content,
                ) as response:
                    await self._check_response(response)
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > self._event_limit:
                            raise CustomerChannelError("response_too_large")
                        data.extend(chunk)
                    try:
                        result = json.loads(data)
                    except (ValueError, RecursionError):
                        raise CustomerChannelError("invalid_response") from None
                    if not isinstance(result, dict):
                        raise CustomerChannelError("invalid_response")
                    return result
        except TimeoutError:
            raise CustomerChannelError("operation_timeout") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise CustomerChannelError("transport_error") from None

    @contextmanager
    def _control_operation(self):
        if self._active:
            raise CustomerChannelError("run_active")
        if self._control_active:
            raise CustomerChannelError("client_busy")
        self._control_active = True
        try:
            yield
        finally:
            self._control_active = False

    async def capabilities(self):
        with self._control_operation():
            result = await self._json("GET", CHANNEL_PATH + "/capabilities")
        if (
            result.get("enabled") is not True
            or result.get("protocol") != PROTOCOL
            or not isinstance(result.get("transports"), list)
            or "http-sse" not in result["transports"]
        ):
            raise CustomerChannelError("unsupported_protocol")
        return {
            key: result.get(key)
            for key in (
                "enabled",
                "protocol",
                "skills",
                "thinking",
                "attachments",
                "long_running_tools",
            )
        }

    @staticmethod
    def _validate_identity(app_name, user_id, session_id):
        for value, limit in ((app_name, 128), (user_id, 256), (session_id, 128)):
            if (
                not isinstance(value, str)
                or not value
                or len(value) > limit
                or value in {".", ".."}
            ):
                raise CustomerChannelError("invalid_session")

    async def session_exists(self, app_name: str, user_id: str, session_id: str):
        """Check one exact session; never return remote history to the caller."""
        self._validate_identity(app_name, user_id, session_id)
        with self._control_operation():
            self._bind((app_name, user_id, session_id))
            path = f"/managed/apps/{quote(app_name, safe='')}/users/{quote(user_id, safe='')}/sessions/{quote(session_id, safe='')}"
            try:
                result = await self._json("GET", path)
            except CustomerChannelError as error:
                if str(error) == "http_status_404":
                    return False
                raise
        if result.get("id") != session_id:
            raise CustomerChannelError("session_mismatch")
        return True

    async def create_session(self, app_name: str, user_id: str, session_id: str):
        self._validate_identity(app_name, user_id, session_id)
        with self._control_operation():
            self._bind((app_name, user_id, session_id))
            path = f"/managed/apps/{quote(app_name, safe='')}/users/{quote(user_id, safe='')}/sessions"
            result = await self._json("POST", path, {"sessionId": session_id})
        if result.get("id") != session_id:
            raise CustomerChannelError("session_mismatch")

    @asynccontextmanager
    async def run(self, request: CustomerRunRequest):
        """Own a stream until terminal/exit; never retry a submitted run."""
        if self._active:
            raise CustomerChannelError("run_active")
        if self._control_active:
            raise CustomerChannelError("client_busy")
        snapshot = CustomerRunRequest.model_validate(
            copy.deepcopy(request.model_dump())
        )
        self._bind((snapshot.app_name, snapshot.user_id, snapshot.session_id))
        content = _encode(snapshot.to_wire(), self._request_limit)
        channel = _Channel(self, snapshot)
        self._active = True
        response = None
        sent = False
        try:
            with anyio.fail_after(self._turn_timeout) as deadline:
                http_request = self._http.build_request(
                    "POST",
                    self._endpoint + CHANNEL_PATH + "/http-runs",
                    headers=await self._request_headers(),
                    content=content,
                )
                sent = True
                try:
                    with anyio.fail_after(self._operation_timeout):
                        response = await self._http.send(http_request, stream=True)
                except TimeoutError:
                    raise CustomerChannelError("operation_timeout") from None
                # Explicit HTTP rejection did not establish a channel.
                if not 200 <= response.status_code < 300:
                    sent = False
                await self._check_response(response)
                if (
                    response.headers.get("content-type", "").split(";")[0].strip()
                    != "text/event-stream"
                ):
                    raise CustomerChannelError("invalid_content_type")
                channel._response = response
                yield channel
        except TimeoutError:
            if not deadline.cancel_called:
                raise
            raise CustomerChannelError("run_timeout") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise CustomerChannelError("transport_error") from None
        finally:
            channel._closed = True
            cleanup_deadline = time.monotonic() + self._cleanup_timeout
            try:
                if sent and not channel._terminal:
                    # Reserve part of the single cleanup budget for stream close.
                    with anyio.move_on_after(self._cleanup_timeout * 0.8, shield=True):
                        try:
                            await self._json(
                                "POST",
                                channel._message_path,
                                {
                                    "type": "run.cancel",
                                    "run_id": snapshot.run_id,
                                },
                            )
                        except CustomerChannelError:
                            pass
            finally:
                try:
                    if response is not None:
                        with anyio.move_on_after(
                            max(0, cleanup_deadline - time.monotonic()), shield=True
                        ):
                            await response.aclose()
                finally:
                    channel._pending.clear()
                    self._active = False


class _Channel:
    """One run's stream and correlation state; no tool execution occurs here."""

    def __init__(self, client, request):
        self._client = client
        self._request = request
        self._response = None
        self._terminal = False
        self._closed = False
        self._reading = False
        self._ready = False
        self._had_error = False
        self._seen: set[str] = set()
        self._pending: dict[str, float] = {}
        self._tools = {tool.name: tool for tool in request.tools}
        self._catalog_revision = request.catalog_revision
        self._message_path = (
            CHANNEL_PATH + f"/http-channels/{request.channel_id}/messages"
        )

    async def events(self) -> AsyncIterator[dict]:
        if self._closed or self._reading:
            raise CustomerChannelError("stream_unavailable")
        self._reading = True
        try:
            async for event in read_events(
                self._response.aiter_bytes(), self._client._event_limit
            ):
                self._accept_event(event)
                yield event
                if self._terminal:
                    return
        except httpx.HTTPError:
            raise CustomerChannelError("transport_error") from None
        if not self._terminal:
            raise CustomerChannelError("incomplete_stream")

    def _accept_event(self, event):
        kind = event.get("type")
        if kind == "channel.ready":
            if (
                self._ready
                or event.get("protocol") != PROTOCOL
                or event.get("transport") != "http-sse"
            ):
                raise CustomerChannelError("invalid_event")
            self._ready = True
            return
        if not self._ready or event.get("run_id") != self._request.run_id:
            raise CustomerChannelError("invalid_event")
        if kind == "run.completed":
            status = event.get("status")
            if not isinstance(status, str) or status not in {
                "success",
                "error",
                "cancelled",
            }:
                raise CustomerChannelError("invalid_event")
            self._terminal = True
            invalid_success = status == "success" and (
                self._had_error or bool(self._pending)
            )
            self._pending.clear()
            if invalid_success:
                raise CustomerChannelError("invalid_success_terminal")
            if status != "success":
                raise CustomerChannelError("run_" + status)
        elif kind == "tool.call":
            self._accept_tool(event)
        elif kind == "tool.cancel":
            request_id = event.get("request_id")
            if not isinstance(request_id, str) or request_id not in self._seen:
                raise CustomerChannelError("invalid_event")
            self._pending.pop(request_id, None)
        elif kind == "run.event":
            if not isinstance(event.get("event"), dict):
                raise CustomerChannelError("invalid_event")
            self._had_error |= any(
                event["event"].get(key)
                for key in (
                    "error",
                    "errorCode",
                    "error_code",
                    "errorMessage",
                    "error_message",
                )
            )
        elif kind != "run.started":
            raise CustomerChannelError("invalid_event")

    def _accept_tool(self, event):
        request_id = event.get("request_id")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise CustomerChannelError("invalid_tool_call")
        if request_id in self._seen:
            raise CustomerChannelError("duplicate_tool_call")
        if len(self._seen) >= 1024 or len(self._pending) >= 64:
            raise CustomerChannelError("too_many_tool_calls")
        name = event.get("tool_name")
        tool = self._tools.get(name) if isinstance(name, str) else None
        deadline = event.get("deadline_ms")
        arguments = event.get("arguments")
        if (
            tool is None
            or event.get("scope_id") != self._request.scope_id
            or event.get("catalog_revision") != self._catalog_revision
            or event.get("executor_revision") != tool.executor_revision
            or type(deadline) is not int
            or not 1 <= deadline <= tool.timeout_ms
            or not isinstance(arguments, dict)
        ):
            raise CustomerChannelError("invalid_tool_call")
        try:
            Draft202012Validator(tool.input_schema).validate(arguments)
        except Exception:
            raise CustomerChannelError("invalid_tool_arguments") from None
        self._seen.add(request_id)
        self._pending[request_id] = time.monotonic() + deadline / 1000

    async def submit_result(
        self, request_id: str, *, content=None, status="success", error=""
    ):
        """Consume before sending; an ambiguous acknowledgement never permits replay."""
        if (
            self._closed
            or self._terminal
            or not isinstance(request_id, str)
            or request_id not in self._pending
        ):
            raise CustomerChannelError("stale_tool_result")
        if (
            not isinstance(status, str)
            or status not in {"success", "error", "denied", "timeout"}
            or not isinstance(error, str)
        ):
            raise CustomerChannelError("invalid_tool_result")
        if time.monotonic() >= self._pending[request_id]:
            self._pending.pop(request_id)
            raise CustomerChannelError("stale_tool_result")
        body = {
            "type": "tool.result",
            "request_id": request_id,
            "run_id": self._request.run_id,
            "scope_id": self._request.scope_id,
            "catalog_revision": self._catalog_revision,
            "status": status,
            "content": content,
            "error": error,
        }
        # Validate size/serialization before consuming, then never restore on I/O failure.
        _encode(body, self._client._request_limit)
        self._pending.pop(request_id)
        response = await self._client._json("POST", self._message_path, body)
        if response.get("accepted") is not True:
            raise CustomerChannelError("result_not_accepted")
