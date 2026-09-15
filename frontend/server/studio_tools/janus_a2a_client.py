# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Minimal BFF-owned standard A2A client for the managed Janus Service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

from frontend.server.studio_tools.browser_observability import emit_browser_event
from veadk.cli.codex_app_server import sandbox_service_url

BrowserLocation = Literal["local", "cloud"]
ContextKey = tuple[str, str, str, str, str]
_SAFE_RESPONSE_METADATA = frozenset(
    {
        "status",
        "actionSummary",
        "targetOrigin",
        "expiresAt",
        "riskLevel",
        "capabilityVersion",
    }
)
_MAX_RESULT_TEXT = 64 * 1024
_APPROVAL_CAPABILITY = "browser-action-approval-v1"
_APPROVAL_EXTENSION_URI = "urn:volcengine:janus:browser-action-approval"
_TASK_CANCEL_CAPABILITY = "janus-task-cancel-v1"
_TASK_CANCEL_EXTENSION_URI = "urn:volcengine:janus:task-cancellation"

logger = logging.getLogger(__name__)


class JanusA2AError(RuntimeError):
    """A safe operational error at the Janus A2A boundary."""


class JanusContextStore:
    """Keep Janus context IDs owner-, session-, and location-bound in the BFF."""

    def __init__(self) -> None:
        self._contexts: dict[ContextKey, tuple[BrowserLocation, str]] = {}
        self._lock = asyncio.Lock()
        self._operation_locks: dict[ContextKey, asyncio.Lock] = {}
        self._operation_refs: dict[ContextKey, int] = {}

    @asynccontextmanager
    async def lease(self, key: ContextKey) -> AsyncIterator[None]:
        """Serialize one context's first bind and later turns without leaking locks."""

        async with self._lock:
            operation_lock = self._operation_locks.setdefault(key, asyncio.Lock())
            self._operation_refs[key] = self._operation_refs.get(key, 0) + 1
        acquired = False
        try:
            await operation_lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                operation_lock.release()
            async with self._lock:
                remaining = self._operation_refs[key] - 1
                if remaining == 0:
                    self._operation_refs.pop(key, None)
                    self._operation_locks.pop(key, None)
                else:
                    self._operation_refs[key] = remaining

    async def get(self, key: ContextKey, location: BrowserLocation) -> str | None:
        async with self._lock:
            binding = self._contexts.get(key)
            if binding is None:
                return None
            bound_location, context_id = binding
            if bound_location != location:
                raise JanusA2AError(
                    f"Browser context is locked to {bound_location}; "
                    f"cannot switch to {location}."
                )
            return context_id

    async def put(
        self,
        key: ContextKey,
        location: BrowserLocation,
        context_id: str,
    ) -> None:
        if not context_id:
            return
        async with self._lock:
            binding = self._contexts.get(key)
            if binding is not None and binding[0] != location:
                raise JanusA2AError(
                    f"Browser context is locked to {binding[0]}; "
                    f"cannot switch to {location}."
                )
            self._contexts[key] = (location, context_id)

    async def discard(self, key: ContextKey, location: BrowserLocation) -> None:
        async with self._lock:
            binding = self._contexts.get(key)
            if binding is not None and binding[0] == location:
                self._contexts.pop(key, None)


@dataclass
class _JanusApproval:
    approval_id: str
    context_key: ContextKey
    browser_location: BrowserLocation
    context_id: str
    action_digest: str
    expires_at: datetime
    used: bool = False


class JanusApprovalStore:
    """Keep opaque Janus approvals outside model-visible Tool results."""

    def __init__(self) -> None:
        self._approvals: dict[str, _JanusApproval] = {}
        self._lock = asyncio.Lock()

    async def put(
        self,
        metadata: Mapping[str, str],
        *,
        context_key: ContextKey,
        browser_location: BrowserLocation,
        context_id: str,
    ) -> None:
        approval_id = metadata["approvalId"]
        expires_at = datetime.fromisoformat(
            metadata["expiresAt"].replace("Z", "+00:00")
        )
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        record = _JanusApproval(
            approval_id=approval_id,
            context_key=context_key,
            browser_location=browser_location,
            context_id=context_id,
            action_digest=metadata["actionDigest"],
            expires_at=expires_at,
        )
        async with self._lock:
            self._approvals[approval_id] = record

    async def claim(
        self,
        approval_id: str,
        *,
        context_key: ContextKey,
        browser_location: BrowserLocation,
        context_id: str,
    ) -> None:
        async with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                raise JanusA2AError("Browser approval is unknown or unavailable.")
            if record.used:
                raise JanusA2AError("Browser approval was already used.")
            if record.expires_at <= datetime.now(tz=UTC):
                raise JanusA2AError("Browser approval expired.")
            if (
                record.context_key != context_key
                or record.browser_location != browser_location
                or record.context_id != context_id
            ):
                raise JanusA2AError("Browser approval context does not match.")
            record.used = True


def _parse_approval_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise JanusA2AError("Janus approval metadata is invalid.")
    required = (
        "approvalId",
        "actionDigest",
        "actionSummary",
        "targetOrigin",
        "riskLevel",
        "expiresAt",
        "capabilityVersion",
    )
    result: dict[str, str] = {}
    for key in required:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise JanusA2AError("Janus approval metadata is incomplete.")
        result[key] = item.strip()
    if len(result["approvalId"]) > 512 or len(result["actionDigest"]) != 64:
        raise JanusA2AError("Janus approval metadata is invalid.")
    if result["capabilityVersion"] != _APPROVAL_CAPABILITY:
        raise JanusA2AError("Janus approval capability version is unsupported.")
    try:
        expires_at = datetime.fromisoformat(result["expiresAt"].replace("Z", "+00:00"))
    except ValueError as error:
        raise JanusA2AError("Janus approval expiry is invalid.") from error
    if expires_at.tzinfo is None or expires_at <= datetime.now(tz=UTC):
        raise JanusA2AError("Janus approval is already expired.")
    return result


class JanusA2AClient:
    """Discover Janus and invoke its fixed standard ``message/send`` endpoint."""

    def __init__(
        self,
        service_url: str,
        *,
        token: str = "",
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
        context_store: JanusContextStore | None = None,
        approval_store: JanusApprovalStore | None = None,
    ) -> None:
        parsed = urlsplit(service_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Janus A2A URL must be an HTTP(S) service origin")
        path = parsed.path.rstrip("/")
        if path.endswith("/a2a"):
            path = path[: -len("/a2a")].rstrip("/")
        self._service_url = urlunsplit(
            (parsed.scheme, parsed.netloc, path, parsed.query, "")
        )
        self._agent_card_url = sandbox_service_url(
            self._service_url,
            "/.well-known/agent-card.json",
        )
        self._a2a_url = sandbox_service_url(self._service_url, "/a2a")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._contexts = context_store or JanusContextStore()
        self._approvals = approval_store or JanusApprovalStore()
        self._discovery_lock = asyncio.Lock()
        self._discovered = False
        self._approval_capability: str | None = None
        self._task_cancel_capability: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _discover(self, client: httpx.AsyncClient) -> None:
        if self._discovered:
            return
        async with self._discovery_lock:
            if self._discovered:
                return
            try:
                response = await client.get(self._agent_card_url)
                response.raise_for_status()
                card = response.json()
            except (httpx.HTTPError, ValueError) as error:
                raise JanusA2AError("Janus Agent Card discovery failed.") from error
            if not isinstance(card, Mapping) or not str(card.get("name") or "").strip():
                raise JanusA2AError("Janus Agent Card is invalid.")
            capabilities = card.get("capabilities")
            extensions = (
                capabilities.get("extensions")
                if isinstance(capabilities, Mapping)
                else None
            )
            if isinstance(extensions, list):
                for extension in extensions:
                    if (
                        isinstance(extension, Mapping)
                        and extension.get("uri") == _APPROVAL_EXTENSION_URI
                        and extension.get("version") == _APPROVAL_CAPABILITY
                    ):
                        self._approval_capability = _APPROVAL_CAPABILITY
                    if (
                        isinstance(extension, Mapping)
                        and extension.get("uri") == _TASK_CANCEL_EXTENSION_URI
                        and extension.get("version") == _TASK_CANCEL_CAPABILITY
                    ):
                        self._task_cancel_capability = _TASK_CANCEL_CAPABILITY
            self._discovered = True

    async def _cancel_browser_task(self, task_id: str) -> None:
        request_id = uuid4().hex
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tasks/cancel",
            "params": {"id": task_id},
        }
        try:
            async with httpx.AsyncClient(
                headers=self._headers(),
                timeout=min(self._timeout_seconds, 10.0),
                transport=self._transport,
            ) as client:
                response = await client.post(self._a2a_url, json=body)
                response.raise_for_status()
                envelope = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise JanusA2AError("Janus A2A task cancellation failed.") from error
        if not isinstance(envelope, Mapping) or envelope.get("error") is not None:
            raise JanusA2AError("Janus A2A task cancellation was rejected.")
        result = envelope.get("result")
        status = result.get("status") if isinstance(result, Mapping) else None
        if (
            not isinstance(result, Mapping)
            or result.get("id") != task_id
            or not isinstance(status, Mapping)
            or status.get("state") != "canceled"
        ):
            raise JanusA2AError("Janus A2A task cancellation response is invalid.")

    async def send_browser_task(
        self,
        *,
        task: str,
        browser_location: BrowserLocation,
        context_key: ContextKey,
        approval_id: str | None = None,
        risk_level: str = "read_only",
    ) -> dict[str, Any]:
        async with self._contexts.lease(context_key):
            return await self._send_browser_task(
                task=task,
                browser_location=browser_location,
                context_key=context_key,
                approval_id=approval_id,
                risk_level=risk_level,
            )

    async def _send_browser_task(
        self,
        *,
        task: str,
        browser_location: BrowserLocation,
        context_key: ContextKey,
        approval_id: str | None = None,
        risk_level: str = "read_only",
    ) -> dict[str, Any]:
        if browser_location not in {"local", "cloud"}:
            raise ValueError("browser_location must be local or cloud")
        task = task.strip()
        if not task:
            raise ValueError("browser task must not be empty")
        if risk_level not in {"read_only", "write_prepare", "high"}:
            raise ValueError("browser risk_level is invalid")
        metadata: dict[str, str] = {"browserLocation": browser_location}
        context_id = await self._contexts.get(context_key, browser_location)
        if context_id is not None:
            emit_browser_event(
                "browser_context_reused",
                reason_code="CONTEXT_REUSED",
                runtime_capability="supported",
                location=browser_location,
                risk=risk_level,
            )
        if approval_id and not context_id:
            raise JanusA2AError("Browser approval has no prepared Janus context.")
        message: dict[str, Any] = {
            "kind": "message",
            "messageId": uuid4().hex,
            "role": "user",
            "parts": [{"kind": "text", "text": task}],
            "metadata": metadata,
        }
        if context_id:
            message["contextId"] = context_id
        request_id = uuid4().hex
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
            "params": {"message": message},
        }
        try:
            async with httpx.AsyncClient(
                headers=self._headers(),
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                await self._discover(client)
                if self._task_cancel_capability != _TASK_CANCEL_CAPABILITY:
                    raise JanusA2AError(
                        "Janus browser task cancellation capability is unavailable."
                    )
                if (
                    risk_level == "high" or approval_id is not None
                ) and self._approval_capability != _APPROVAL_CAPABILITY:
                    raise JanusA2AError(
                        "Janus browser action approval capability is unavailable."
                    )
                if approval_id is not None:
                    assert context_id is not None
                    await self._approvals.claim(
                        approval_id,
                        context_key=context_key,
                        browser_location=browser_location,
                        context_id=context_id,
                    )
                    metadata["approvalId"] = approval_id
                    message["metadata"] = metadata
                try:
                    response = await client.post(self._a2a_url, json=body)
                except asyncio.CancelledError:
                    cancellation = asyncio.create_task(
                        self._cancel_browser_task(request_id)
                    )
                    cancellation_succeeded = False
                    try:
                        await asyncio.shield(cancellation)
                        cancellation_succeeded = True
                    except asyncio.CancelledError:
                        try:
                            await cancellation
                            cancellation_succeeded = True
                        except JanusA2AError:
                            logger.exception(
                                "Janus A2A task cancellation propagation failed"
                            )
                    except JanusA2AError:
                        logger.exception(
                            "Janus A2A task cancellation propagation failed"
                        )
                    if cancellation_succeeded:
                        await self._contexts.discard(context_key, browser_location)
                        emit_browser_event(
                            "browser_context_closed",
                            reason_code="TASK_CANCELLED",
                            runtime_capability="supported",
                            location=browser_location,
                            risk=risk_level,
                        )
                    raise
                response.raise_for_status()
                envelope = response.json()
        except JanusA2AError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise JanusA2AError("Janus A2A request failed.") from error
        if not isinstance(envelope, Mapping):
            raise JanusA2AError("Janus A2A returned an invalid response.")
        if envelope.get("error") is not None:
            raise JanusA2AError("Janus A2A rejected the browser task.")
        result = envelope.get("result")
        if not isinstance(result, Mapping):
            raise JanusA2AError("Janus A2A response is missing a result message.")
        parts = result.get("parts")
        if not isinstance(parts, list):
            raise JanusA2AError("Janus A2A result is missing message parts.")
        text = "\n".join(
            str(part.get("text"))
            for part in parts
            if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        ).strip()
        if not text:
            raise JanusA2AError("Janus A2A returned no usable browser result.")
        text = text[:_MAX_RESULT_TEXT]
        returned_context = result.get("contextId")
        if isinstance(returned_context, str) and returned_context.strip():
            returned_context = returned_context.strip()
            await self._contexts.put(context_key, browser_location, returned_context)
            if context_id is None:
                emit_browser_event(
                    "browser_context_created",
                    reason_code="CONTEXT_CREATED",
                    runtime_capability="supported",
                    location=browser_location,
                    risk=risk_level,
                )
        else:
            returned_context = None
        raw_metadata = result.get("metadata")
        safe_metadata = (
            {
                str(key): value
                for key, value in raw_metadata.items()
                if key in _SAFE_RESPONSE_METADATA
            }
            if isinstance(raw_metadata, Mapping)
            else {}
        )
        status = str(safe_metadata.get("status") or "completed")
        output = {
            "status": status,
            "text": text,
            "contextId": returned_context,
            "metadata": safe_metadata,
        }
        if status == "approval_required":
            approval = _parse_approval_metadata(raw_metadata)
            if returned_context is None:
                raise JanusA2AError(
                    "Janus approval response is missing its browser context."
                )
            await self._approvals.put(
                approval,
                context_key=context_key,
                browser_location=browser_location,
                context_id=returned_context,
            )
            output["approval"] = approval
        return output


__all__ = [
    "JanusA2AClient",
    "JanusA2AError",
    "JanusApprovalStore",
    "JanusContextStore",
]
