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

"""Resolve one managed Janus Sandbox Session for each trusted Studio owner."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from frontend.server.studio_tools.janus_a2a_client import JanusA2AClient
from frontend.server.studio_tools.registry import StudioToolExecutionContext
from frontend.server.studio_tools.sandbox_shell import SandboxResolutionError
from veadk.cli.agentkit_session_metadata import build_create_session_request

_READY_STATUS = "ready"
_FAILED_STATUSES = frozenset({"error", "failed", "createfailed", "deleting", "deleted"})
_SESSION_TTL_SECONDS = 4 * 60 * 60
_SESSION_READY_TIMEOUT_SECONDS = 90
_POLL_INTERVAL_SECONDS = 2.0
_MAX_CACHED_OWNERS = 1_024
_LOCK_STRIPES = 64


class JanusSandboxResolutionError(SandboxResolutionError):
    """A safe failure while preparing an owner-bound Janus Sandbox."""


@dataclass(frozen=True)
class _CachedClient:
    session_id: str
    endpoint: str
    client: JanusA2AClient


class AgentkitJanusSandboxResolver:
    """Create or restore one private Janus Session per Studio owner.

    The resolver owns only Janus lifecycle and routing. Ordinary mounted
    environments continue to use ``AgentkitEnvironmentSandboxResolver``.
    """

    def __init__(
        self,
        client_factory: Callable[[str, str], Any],
        *,
        tool_id: str,
        provider: str,
        region: str,
        sleep: Callable[[float], Any] = asyncio.sleep,
        poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
        max_cached_owners: int = _MAX_CACHED_OWNERS,
    ) -> None:
        self._client_factory = client_factory
        self._tool_id = tool_id.strip()
        self._provider = provider.strip()
        self._region = region.strip()
        self._sleep = sleep
        self._poll_interval_seconds = poll_interval_seconds
        self._max_cached_owners = max(1, max_cached_owners)
        self._clients: OrderedDict[str, _CachedClient] = OrderedDict()
        # Fixed stripes avoid retaining one lock for every customer forever.
        self._locks = tuple(asyncio.Lock() for _ in range(_LOCK_STRIPES))

    async def prepare(self, context: StudioToolExecutionContext) -> JanusA2AClient:
        """Return the Janus client bound to the context's trusted owner."""

        if not self._tool_id or not self._provider or not self._region:
            raise JanusSandboxResolutionError(
                "Managed Janus Sandbox target is not configured."
            )
        owner_id = context.owner_id.strip()
        if not owner_id:
            raise JanusSandboxResolutionError(
                "Managed Janus Sandbox owner identity is unavailable."
            )
        if len(owner_id.encode("utf-8")) > 1_024:
            raise JanusSandboxResolutionError(
                "Managed Janus Sandbox owner identity is invalid."
            )
        owner_key = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()
        lock = self._locks[int(owner_key[:8], 16) % len(self._locks)]
        async with lock:
            try:
                platform_client = self._client_factory(self._provider, self._region)
                await _require_ready_tool(platform_client, self._tool_id)
                cached = self._clients.get(owner_key)
                if cached is not None:
                    endpoint = await _ready_cached_endpoint(
                        platform_client,
                        tool_id=self._tool_id,
                        session_id=cached.session_id,
                    )
                    if endpoint:
                        if endpoint != cached.endpoint:
                            cached = _CachedClient(
                                session_id=cached.session_id,
                                endpoint=endpoint,
                                client=JanusA2AClient(endpoint),
                            )
                            self._clients[owner_key] = cached
                        self._clients.move_to_end(owner_key)
                        return cached.client
                    self._clients.pop(owner_key, None)
                session = await self._session_for_owner(
                    platform_client,
                    owner_id=owner_id,
                    owner_key=owner_key,
                )
                binding = _CachedClient(
                    session_id=session.session_id,
                    endpoint=session.endpoint,
                    client=JanusA2AClient(session.endpoint),
                )
                self._clients[owner_key] = binding
                self._clients.move_to_end(owner_key)
                while len(self._clients) > self._max_cached_owners:
                    self._clients.popitem(last=False)
                return binding.client
            except JanusSandboxResolutionError:
                raise
            except Exception as error:
                # AgentKit exceptions may contain private data-plane endpoints.
                raise JanusSandboxResolutionError(
                    "Managed Janus Sandbox Session could not be prepared."
                ) from error

    async def _session_for_owner(
        self,
        client: Any,
        *,
        owner_id: str,
        owner_key: str,
    ) -> _ReadySession:
        from agentkit.sdk.tools import types as tools_types

        user_session_id = _user_session_id(self._tool_id, owner_key)
        existing = await asyncio.to_thread(
            _find_session,
            client,
            tools_types,
            self._tool_id,
            user_session_id,
        )
        if existing is None:
            request = build_create_session_request(
                tool_id=self._tool_id,
                ttl_seconds=_SESSION_TTL_SECONDS,
                user_session_id=user_session_id,
                display_name="Studio Browser Janus",
                agent_kind="janus-browser-use",
                envs={"JANUS_A2A_OWNER_ID": owner_id},
            )
            try:
                existing = await asyncio.to_thread(client.create_session, request)
            except Exception:
                existing = await asyncio.to_thread(
                    _find_session,
                    client,
                    tools_types,
                    self._tool_id,
                    user_session_id,
                )
                if existing is None:
                    raise
        return await _wait_for_ready_session(
            client,
            tools_types,
            tool_id=self._tool_id,
            session=existing,
            sleep=self._sleep,
            poll_interval_seconds=self._poll_interval_seconds,
        )


@dataclass(frozen=True)
class _ReadySession:
    session_id: str
    endpoint: str


def _user_session_id(tool_id: str, owner_key: str) -> str:
    digest = hashlib.sha256(f"{tool_id}\0{owner_key}".encode()).hexdigest()[:32]
    return f"studio-janus-v1-{digest}"


def _find_session(
    client: Any,
    tools_types: Any,
    tool_id: str,
    user_session_id: str,
) -> Any | None:
    response = client.list_sessions(
        tools_types.ListSessionsRequest(
            ToolId=tool_id,
            MaxResults=10,
            Filters=[
                tools_types.FiltersItemForListSessions(
                    Name="UserSessionId",
                    Values=[user_session_id],
                )
            ],
        )
    )
    for session in getattr(response, "session_infos", None) or []:
        if str(getattr(session, "user_session_id", "") or "") != user_session_id:
            continue
        status = str(getattr(session, "status", "") or "").strip().lower()
        if status not in _FAILED_STATUSES:
            return session
    return None


async def _require_ready_tool(client: Any, tool_id: str) -> None:
    from agentkit.sdk.tools import types as tools_types

    try:
        tool = await asyncio.to_thread(
            client.get_tool,
            tools_types.GetToolRequest(ToolId=tool_id),
        )
    except Exception as error:
        raise JanusSandboxResolutionError(
            "Managed Janus Sandbox Tool is unavailable."
        ) from error
    status = str(getattr(tool, "status", "") or "").strip().lower()
    if status != _READY_STATUS:
        raise JanusSandboxResolutionError("Managed Janus Sandbox Tool is not Ready.")


async def _ready_cached_endpoint(
    client: Any,
    *,
    tool_id: str,
    session_id: str,
) -> str:
    from agentkit.sdk.tools import types as tools_types

    try:
        session = await asyncio.to_thread(
            client.get_session,
            tools_types.GetSessionRequest(ToolId=tool_id, SessionId=session_id),
        )
    except Exception:
        return ""
    status = str(getattr(session, "status", "") or "").strip().lower()
    endpoint = str(getattr(session, "endpoint", "") or "").strip()
    return endpoint if status == _READY_STATUS and _valid_endpoint(endpoint) else ""


async def _wait_for_ready_session(
    client: Any,
    tools_types: Any,
    *,
    tool_id: str,
    session: Any,
    sleep: Callable[[float], Any],
    poll_interval_seconds: float,
) -> _ReadySession:
    session_id = str(getattr(session, "session_id", "") or "").strip()
    if not session_id:
        raise JanusSandboxResolutionError(
            "AgentKit did not return a Janus Sandbox Session ID."
        )
    endpoint = str(getattr(session, "endpoint", "") or "").strip()
    status = str(getattr(session, "status", "") or "").strip().lower()
    deadline = time.monotonic() + _SESSION_READY_TIMEOUT_SECONDS
    while status != _READY_STATUS or not endpoint:
        if status in _FAILED_STATUSES:
            raise JanusSandboxResolutionError(
                "Managed Janus Sandbox Session failed to become ready."
            )
        if time.monotonic() >= deadline:
            raise JanusSandboxResolutionError(
                "Timed out waiting for the managed Janus Sandbox Session."
            )
        await sleep(poll_interval_seconds)
        session = await asyncio.to_thread(
            client.get_session,
            tools_types.GetSessionRequest(ToolId=tool_id, SessionId=session_id),
        )
        endpoint = str(getattr(session, "endpoint", "") or "").strip()
        status = str(getattr(session, "status", "") or "").strip().lower()
    if not _valid_endpoint(endpoint):
        raise JanusSandboxResolutionError(
            "Managed Janus Sandbox returned an invalid endpoint."
        )
    return _ReadySession(session_id=session_id, endpoint=endpoint)


def _valid_endpoint(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


__all__ = [
    "AgentkitJanusSandboxResolver",
    "JanusSandboxResolutionError",
]
