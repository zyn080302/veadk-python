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

"""Automatic Browser Use Tool backed by the owner-bound Janus A2A Service."""

from __future__ import annotations

from time import monotonic
from typing import Any, cast

from frontend.server.studio_tools.browser_observability import emit_browser_event
from frontend.server.studio_tools.janus_a2a_client import (
    BrowserLocation,
    JanusA2AError,
)
from frontend.server.studio_tools.registry import (
    StudioTool,
    StudioToolExecutionContext,
    StudioToolExecutionError,
    StudioToolRegistry,
    StudioToolRuntimeError,
)


async def _browser_use(
    arguments: dict[str, Any],
    context: StudioToolExecutionContext,
) -> dict[str, Any]:
    plan = context.tool_plan
    if plan.get("decision") != "mount":
        raise StudioToolExecutionError(
            "Browser Use is unavailable without a trusted run ToolPlan."
        )
    location = plan.get("browser_location")
    if location not in {"local", "cloud"}:
        raise StudioToolExecutionError(
            "Browser Use run ToolPlan is missing a trusted browser location."
        )
    risk_level = plan.get("risk_level")
    if risk_level not in {"read_only", "write_prepare", "high"}:
        raise StudioToolExecutionError(
            "Browser Use run ToolPlan has an invalid trusted risk level."
        )
    task = str(arguments.get("task") or "").strip()
    if not task:
        raise StudioToolExecutionError("Browser Use task must not be empty.")
    approval_id = plan.get("approval_id")
    if approval_id is not None and not isinstance(approval_id, str):
        raise StudioToolExecutionError("Browser Use approval state is invalid.")
    janus_client = context.janus_client
    if janus_client is None:
        raise StudioToolExecutionError(
            "The owner-bound Janus Sandbox was not prepared for this run."
        )
    event_dimensions = {
        "reason_code": str(plan.get("reason_code") or "UNSPECIFIED"),
        "runtime_capability": "supported",
        "location": location,
        "risk": risk_level,
        "catalog_revision": context.catalog_revision,
        "legacy_agent": False,
    }
    if approval_id is not None:
        emit_browser_event(
            "browser_approval_approved",
            **event_dimensions,
        )
    started_at = monotonic()
    emit_browser_event("browser_a2a_started", **event_dimensions)
    if context.report_progress is not None:
        await context.report_progress(
            {
                "phase": "browser_a2a_started",
                "browserLocation": location,
            }
        )
    try:
        result = await janus_client.send_browser_task(
            task=task,
            browser_location=cast(BrowserLocation, location),
            approval_id=approval_id,
            risk_level=cast(str, risk_level),
            context_key=(
                context.owner_id,
                context.runtime_id,
                context.app_name,
                context.user_id,
                context.session_id,
            ),
        )
    except (JanusA2AError, ValueError) as error:
        emit_browser_event(
            "browser_a2a_failed",
            latency_ms=(monotonic() - started_at) * 1000,
            error_class=type(error).__name__,
            **event_dimensions,
        )
        raise StudioToolRuntimeError(str(error)) from error
    approval = result.get("approval")
    if result["status"] == "approval_required":
        if not isinstance(approval, dict):
            raise StudioToolRuntimeError(
                "Janus Browser approval response is incomplete."
            )
        if context.report_progress is not None:
            await context.report_progress(
                {
                    "phase": "browser_approval_required",
                    "browserLocation": location,
                    "status": "approval_required",
                    "approval": approval,
                }
            )
        emit_browser_event(
            "browser_approval_requested",
            latency_ms=(monotonic() - started_at) * 1000,
            **event_dimensions,
        )
    elif context.report_progress is not None:
        await context.report_progress(
            {
                "phase": "browser_a2a_completed",
                "browserLocation": location,
                "status": result["status"],
            }
        )
    if result["status"] != "approval_required":
        emit_browser_event(
            "browser_a2a_completed",
            latency_ms=(monotonic() - started_at) * 1000,
            **event_dimensions,
        )
    # contextId remains in the BFF store and is never made model-configurable.
    return {
        "status": result["status"],
        "text": result["text"],
        "metadata": result["metadata"],
    }


def register_tools(registry: StudioToolRegistry) -> None:
    registry.register(
        StudioTool(
            name="browser_use",
            display_name="浏览器自动化",
            description=(
                "Complete a browser task through the owner-bound managed Janus "
                "A2A Service."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 16_384,
                        "description": "The outcome-oriented browser task.",
                    }
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            executor=_browser_use,
            executor_revision="janus-a2a-browser-use-v1",
            timeout_ms=120_000,
            idempotent=False,
            risk_level="high",
            requires_context=True,
            activation_mode="automatic",
        )
    )


__all__ = ["register_tools"]
