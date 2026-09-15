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

import re
from typing import Any
from types import ModuleType, SimpleNamespace

import pytest

from frontend.server.studio_tools import extensions
from frontend.server.studio_tools.extensions import register_studio_tool_extensions
from frontend.server.studio_tools.registry import (
    StudioToolExecutionContext,
    StudioToolExecutionError,
    StudioToolRegistry,
)


@pytest.mark.asyncio
async def test_current_time_extension_is_discovered_and_executable() -> None:
    registry = StudioToolRegistry()

    register_studio_tool_extensions(registry)

    assert registry.public_items() == [
        {
            "id": "browser_use",
            "name": "浏览器自动化",
            "description": (
                "Complete a browser task through the owner-bound managed Janus "
                "A2A Service."
            ),
            "riskLevel": "high",
            "activationMode": "automatic",
        },
        {
            "id": "current_time",
            "name": "当前时间",
            "description": "Return the current date and time in an IANA timezone.",
            "riskLevel": "low",
        },
    ]
    result = await registry.execute(
        name="current_time",
        executor_revision="studio-extension-current-time-v1",
        arguments={"timezone": "UTC"},
    )
    assert result["timezone"] == "UTC"
    assert result["iso8601"].endswith("+00:00")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result["date"])
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", result["time"])


@pytest.mark.asyncio
async def test_browser_use_extension_uses_only_the_trusted_run_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from frontend.server.studio_tools.extensions import browser_use

    calls: list[dict[str, object]] = []
    events: list[tuple[str, dict[str, object]]] = []

    class _Client:
        async def send_browser_task(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {
                "status": "completed",
                "text": "Example Domain",
                "contextId": "context-secret",
                "metadata": {},
            }

    monkeypatch.setattr(
        browser_use,
        "emit_browser_event",
        lambda event, **fields: events.append((event, fields)),
    )
    registry = StudioToolRegistry()
    browser_use.register_tools(registry)

    context = StudioToolExecutionContext(
        runtime_id="runtime-1",
        app_name="agent",
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision=registry.revision,
        owner_id="owner-1",
        tool_plan={
            "decision": "mount",
            "browser_location": "cloud",
            "risk_level": "high",
            "approval_id": "approval-1",
        },
        janus_client=_Client(),
    )

    result = await registry.execute(
        name="browser_use",
        executor_revision="janus-a2a-browser-use-v1",
        arguments={"task": "Open example.com"},
        context=context,
    )

    assert calls == [
        {
            "task": "Open example.com",
            "browser_location": "cloud",
            "approval_id": "approval-1",
            "risk_level": "high",
            "context_key": (
                "owner-1",
                "runtime-1",
                "agent",
                "user-1",
                "session-1",
            ),
        }
    ]
    assert result == {
        "status": "completed",
        "text": "Example Domain",
        "metadata": {},
    }
    assert [event for event, _fields in events] == [
        "browser_approval_approved",
        "browser_a2a_started",
        "browser_a2a_completed",
    ]
    assert "Open example.com" not in repr(events)


@pytest.mark.asyncio
async def test_browser_use_keeps_approval_secret_out_of_model_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from frontend.server.studio_tools.extensions import browser_use

    progress: list[dict[str, Any]] = []
    approval = {
        "approvalId": "approval-opaque",
        "actionDigest": "a" * 64,
        "actionSummary": "发布公告",
        "targetOrigin": "https://example.com",
        "riskLevel": "high",
        "expiresAt": "2026-09-15T12:00:00Z",
        "capabilityVersion": "browser-action-approval-v1",
    }

    class _Client:
        async def send_browser_task(self, **_kwargs: object) -> dict[str, object]:
            return {
                "status": "approval_required",
                "text": "发布前需要确认。",
                "contextId": "private-context",
                "metadata": {
                    "status": "approval_required",
                    "actionSummary": "发布公告",
                    "targetOrigin": "https://example.com",
                    "riskLevel": "high",
                    "expiresAt": "2026-09-15T12:00:00Z",
                    "capabilityVersion": "browser-action-approval-v1",
                },
                "approval": approval,
            }

    registry = StudioToolRegistry()
    browser_use.register_tools(registry)

    async def report_progress(event: dict[str, Any]) -> None:
        progress.append(event)

    context = StudioToolExecutionContext(
        runtime_id="runtime-1",
        app_name="agent",
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision=registry.revision,
        owner_id="owner-1",
        tool_plan={
            "decision": "mount",
            "browser_location": "cloud",
            "risk_level": "high",
            "approval_id": None,
        },
        report_progress=report_progress,
        janus_client=_Client(),
    )

    result = await registry.execute(
        name="browser_use",
        executor_revision="janus-a2a-browser-use-v1",
        arguments={"task": "发布公告"},
        context=context,
    )

    assert progress == [
        {
            "phase": "browser_a2a_started",
            "browserLocation": "cloud",
        },
        {
            "phase": "browser_approval_required",
            "browserLocation": "cloud",
            "status": "approval_required",
            "approval": approval,
        },
    ]
    assert result == {
        "status": "approval_required",
        "text": "发布前需要确认。",
        "metadata": {
            "status": "approval_required",
            "actionSummary": "发布公告",
            "targetOrigin": "https://example.com",
            "riskLevel": "high",
            "expiresAt": "2026-09-15T12:00:00Z",
            "capabilityVersion": "browser-action-approval-v1",
        },
    }
    assert "approval-opaque" not in repr(result)
    assert "a" * 64 not in repr(result)


@pytest.mark.asyncio
async def test_browser_use_fails_closed_without_owner_bound_janus_client() -> None:
    from frontend.server.studio_tools.extensions import browser_use

    registry = StudioToolRegistry()
    browser_use.register_tools(registry)
    context = StudioToolExecutionContext(
        runtime_id="runtime-1",
        app_name="agent",
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision=registry.revision,
        owner_id="owner-1",
        tool_plan={
            "decision": "mount",
            "browser_location": "cloud",
            "risk_level": "read_only",
        },
    )

    with pytest.raises(
        StudioToolExecutionError,
        match="owner-bound Janus Sandbox was not prepared",
    ):
        await registry.execute(
            name="browser_use",
            executor_revision="janus-a2a-browser-use-v1",
            arguments={"task": "Open example.com"},
            context=context,
        )


@pytest.mark.asyncio
async def test_current_time_extension_rejects_unknown_timezone() -> None:
    registry = StudioToolRegistry()
    register_studio_tool_extensions(registry)

    with pytest.raises(StudioToolExecutionError, match="Unknown IANA timezone"):
        await registry.execute(
            name="current_time",
            executor_revision="studio-extension-current-time-v1",
            arguments={"timezone": "Mars/Olympus_Mons"},
        )


def test_extension_discovery_is_sorted_and_ignores_private_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []
    registered: list[str] = []

    monkeypatch.setattr(
        extensions,
        "iter_modules",
        lambda paths: [
            SimpleNamespace(name="z_last", ispkg=False),
            SimpleNamespace(name="_template", ispkg=False),
            SimpleNamespace(name="nested", ispkg=True),
            SimpleNamespace(name="a_first", ispkg=False),
        ],
    )

    def fake_import_module(name: str) -> ModuleType:
        imported.append(name)
        module = ModuleType(name)
        module.register_tools = lambda registry: registered.append(name)  # type: ignore[attr-defined]
        return module

    monkeypatch.setattr(extensions, "import_module", fake_import_module)

    register_studio_tool_extensions(StudioToolRegistry())

    assert imported == [
        "frontend.server.studio_tools.extensions.a_first",
        "frontend.server.studio_tools.extensions.z_last",
    ]
    assert registered == imported


def test_extension_discovery_rejects_module_without_registration_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        extensions,
        "iter_modules",
        lambda paths: [SimpleNamespace(name="invalid", ispkg=False)],
    )
    monkeypatch.setattr(
        extensions,
        "import_module",
        lambda name: ModuleType(name),
    )

    with pytest.raises(RuntimeError, match=r"must export register_tools\(registry\)"):
        register_studio_tool_extensions(StudioToolRegistry())
