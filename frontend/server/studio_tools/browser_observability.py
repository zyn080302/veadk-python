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

"""Bounded, structured, and content-free Browser Use audit events."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_NAMES = frozenset(
    {
        "browser_tool_plan_created",
        "browser_tool_mounted",
        "browser_tool_not_mounted",
        "browser_environment_selected",
        "browser_a2a_started",
        "browser_a2a_completed",
        "browser_a2a_failed",
        "browser_approval_requested",
        "browser_approval_approved",
        "browser_approval_rejected",
        "browser_approval_expired",
        "browser_context_created",
        "browser_context_reused",
        "browser_context_closed",
        "browser_unknown_tool_recovered",
    }
)
_LABEL_RE = re.compile(r"[^A-Za-z0-9_.:@/-]+")


def _label(value: object, fallback: str) -> str:
    normalized = _LABEL_RE.sub("_", str(value or "").strip())[:128]
    return normalized or fallback


def emit_browser_event(
    event: str,
    *,
    reason_code: str = "UNSPECIFIED",
    runtime_capability: str = "unknown",
    location: str = "none",
    risk: str = "none",
    latency_ms: float = 0,
    error_class: str = "none",
    catalog_revision: str = "unknown",
    legacy_agent: bool = False,
) -> None:
    """Emit only fixed low-cardinality dimensions, never task or page content."""

    if event not in _EVENT_NAMES:
        raise ValueError(f"unsupported Browser Use event: {event}")
    normalized_latency = float(latency_ms)
    if not math.isfinite(normalized_latency) or normalized_latency < 0:
        normalized_latency = 0
    logger.info(
        "browser_use_event",
        extra={
            "browser_event": event,
            "reason_code": _label(reason_code, "UNSPECIFIED"),
            "runtime_capability": _label(runtime_capability, "unknown"),
            "location": _label(location, "none"),
            "risk": _label(risk, "none"),
            "latency_ms": round(normalized_latency, 3),
            "error_class": _label(error_class, "none"),
            "catalog_revision": _label(catalog_revision, "unknown"),
            "legacy_agent": bool(legacy_agent),
        },
    )


def emit_browser_plan_events(
    plan: Any,
    *,
    mounted: bool,
    runtime_capability: str,
    catalog_revision: str,
) -> None:
    """Emit the final per-Run plan outcome after Tool Host negotiation."""

    dimensions = {
        "reason_code": str(getattr(plan, "reason_code", "") or "UNSPECIFIED"),
        "runtime_capability": runtime_capability,
        "location": str(getattr(plan, "browser_location", "") or "none"),
        "risk": str(getattr(plan, "risk_level", "") or "none"),
        "catalog_revision": catalog_revision,
        "legacy_agent": (
            getattr(plan, "reason_code", "") == "LEGACY_STATIC_BROWSER_AGENT"
        ),
    }
    emit_browser_event("browser_tool_plan_created", **dimensions)
    if dimensions["location"] != "none":
        emit_browser_event("browser_environment_selected", **dimensions)
    emit_browser_event(
        "browser_tool_mounted" if mounted else "browser_tool_not_mounted",
        **dimensions,
    )


__all__ = ["emit_browser_event", "emit_browser_plan_events"]
