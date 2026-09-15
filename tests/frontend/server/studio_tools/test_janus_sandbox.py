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

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from frontend.server.studio_tools.janus_sandbox import (
    AgentkitJanusSandboxResolver,
    JanusSandboxResolutionError,
)
from frontend.server.studio_tools.registry import StudioToolExecutionContext


def _context(
    owner_id: str, session_id: str = "conversation-1"
) -> StudioToolExecutionContext:
    return StudioToolExecutionContext(
        runtime_id="runtime-1",
        app_name="app-1",
        user_id="user-1",
        session_id=session_id,
        run_id="run-1",
        scope_id=f"scope-{session_id}",
        catalog_revision="revision-1",
        owner_id=owner_id,
    )


class _FakeAgentkitClient:
    def __init__(self) -> None:
        self.tool = SimpleNamespace(
            tool_id="janus-tool",
            image_url="registry.example/janus@sha256:abc",
            status="Ready",
        )
        self.sessions: list[Any] = []
        self.created_sessions: list[Any] = []

    def get_tool(self, request: Any) -> Any:
        assert request.tool_id == self.tool.tool_id
        return self.tool

    def list_sessions(self, request: Any) -> Any:
        user_session_id = request.filters[0].values[0]
        return SimpleNamespace(
            session_infos=[
                session
                for session in self.sessions
                if session.tool_id == request.tool_id
                and session.user_session_id == user_session_id
            ]
        )

    def create_session(self, request: Any) -> Any:
        self.created_sessions.append(request)
        sequence = len(self.created_sessions)
        session = SimpleNamespace(
            session_id=f"janus-session-{sequence}",
            tool_id=request.tool_id,
            user_session_id=request.user_session_id,
            endpoint=(
                f"https://sandbox-{sequence}.example/base"
                f"?Authorization=private-{sequence}"
            ),
            status="Ready",
        )
        self.sessions.append(session)
        return session

    def get_session(self, request: Any) -> Any:
        return next(
            session
            for session in self.sessions
            if session.session_id == request.session_id
        )


def _session_envs(request: Any) -> dict[str, str]:
    return {item.key: item.value for item in request.envs}


@pytest.mark.asyncio
async def test_resolver_creates_distinct_owner_bound_sessions_and_reuses_owner() -> (
    None
):
    client = _FakeAgentkitClient()
    resolver = AgentkitJanusSandboxResolver(
        lambda provider, region: client,
        tool_id="janus-tool",
        provider="volcengine",
        region="cn-beijing",
        poll_interval_seconds=0,
    )

    owner_one = await resolver.prepare(_context("owner-one"))
    owner_one_again = await resolver.prepare(
        _context("owner-one", session_id="conversation-2")
    )
    owner_two = await resolver.prepare(_context("owner-two"))

    assert owner_one is owner_one_again
    assert owner_one is not owner_two
    assert len(client.created_sessions) == 2
    assert [_session_envs(request) for request in client.created_sessions] == [
        {"JANUS_A2A_OWNER_ID": "owner-one"},
        {"JANUS_A2A_OWNER_ID": "owner-two"},
    ]
    first_id, second_id = [
        request.user_session_id for request in client.created_sessions
    ]
    assert first_id != second_id
    assert "owner-one" not in first_id
    assert "owner-two" not in second_id


@pytest.mark.asyncio
async def test_resolver_serializes_concurrent_first_session_for_same_owner() -> None:
    client = _FakeAgentkitClient()
    resolver = AgentkitJanusSandboxResolver(
        lambda provider, region: client,
        tool_id="janus-tool",
        provider="volcengine",
        region="cn-beijing",
        poll_interval_seconds=0,
    )

    first, second = await asyncio.gather(
        resolver.prepare(_context("owner-one")),
        resolver.prepare(_context("owner-one", "conversation-2")),
    )

    assert first is second
    assert len(client.created_sessions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_id", "provider", "region"),
    [
        ("", "volcengine", "cn-beijing"),
        ("janus-tool", "", "cn-beijing"),
        ("janus-tool", "volcengine", ""),
    ],
)
async def test_resolver_fails_closed_when_platform_target_is_incomplete(
    tool_id: str,
    provider: str,
    region: str,
) -> None:
    resolver = AgentkitJanusSandboxResolver(
        lambda _provider, _region: _FakeAgentkitClient(),
        tool_id=tool_id,
        provider=provider,
        region=region,
        poll_interval_seconds=0,
    )

    with pytest.raises(JanusSandboxResolutionError, match="not configured"):
        await resolver.prepare(_context("owner-one"))


@pytest.mark.asyncio
async def test_resolver_rejects_missing_owner_without_platform_calls() -> None:
    calls: list[tuple[str, str]] = []
    resolver = AgentkitJanusSandboxResolver(
        lambda provider, region: calls.append((provider, region)),
        tool_id="janus-tool",
        provider="volcengine",
        region="cn-beijing",
        poll_interval_seconds=0,
    )

    with pytest.raises(JanusSandboxResolutionError, match="owner identity"):
        await resolver.prepare(_context(""))

    assert calls == []
