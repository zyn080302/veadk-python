from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from frontend.server.studio_tools.browser_observability import (
    emit_browser_event,
    emit_browser_plan_events,
)


def test_browser_event_is_structured_and_cannot_include_prompt_or_page_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="frontend.server.studio_tools.browser_observability",
    )

    emit_browser_event(
        "browser_tool_plan_created",
        reason_code="PUBLIC_WEB_TASK",
        runtime_capability="supported",
        location="cloud",
        risk="read_only",
        latency_ms=12.5,
        error_class="none",
        catalog_revision="sha256:catalog",
        legacy_agent=False,
    )

    record = caplog.records[-1]
    assert record.getMessage() == "browser_use_event"
    assert record.browser_event == "browser_tool_plan_created"
    assert record.reason_code == "PUBLIC_WEB_TASK"
    assert record.runtime_capability == "supported"
    assert record.location == "cloud"
    assert record.risk == "read_only"
    assert record.latency_ms == 12.5
    assert record.error_class == "none"
    assert record.catalog_revision == "sha256:catalog"
    assert record.legacy_agent is False
    assert "prompt" not in record.__dict__
    assert "url" not in record.__dict__
    assert "page" not in record.__dict__


def test_browser_event_rejects_unknown_event_name() -> None:
    with pytest.raises(ValueError, match="unsupported Browser Use event"):
        emit_browser_event("raw_prompt_dump")


def test_final_plan_events_distinguish_planned_environment_from_actual_mount(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="frontend.server.studio_tools.browser_observability",
    )

    emit_browser_plan_events(
        SimpleNamespace(
            reason_code="RUNTIME_TOOL_HOST_UNAVAILABLE",
            browser_location="cloud",
            risk_level="read_only",
        ),
        mounted=False,
        runtime_capability="unsupported",
        catalog_revision="sha256:catalog",
    )

    assert [record.browser_event for record in caplog.records[-3:]] == [
        "browser_tool_plan_created",
        "browser_environment_selected",
        "browser_tool_not_mounted",
    ]
