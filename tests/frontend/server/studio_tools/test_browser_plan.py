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

from types import SimpleNamespace

import pytest

from frontend.server.studio_tools.browser_plan import (
    BrowserRolloutContext,
    ToolPolicyError,
    resolve_run_tool_plan,
    runtime_has_legacy_static_browser,
    studio_tool_plan_sse_event,
)
from frontend.server.studio_tools.registry import StudioTool, StudioToolRegistry


def _registry() -> StudioToolRegistry:
    registry = StudioToolRegistry()
    registry.register(
        StudioTool(
            name="current_time",
            description="Return the current time.",
            input_schema={"type": "object", "properties": {}},
            executor=lambda arguments: arguments,
        )
    )
    registry.register(
        StudioTool(
            name="browser_use",
            description="Operate a browser through Janus.",
            input_schema={
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
            executor=lambda arguments: arguments,
            activation_mode="automatic",
        )
    )
    return registry


def _payload(text: str, **policy: object) -> dict[str, object]:
    return {
        "new_message": {"role": "user", "parts": [{"text": text}]},
        "tool_policy": {"mode": "auto", **policy},
    }


@pytest.fixture(autouse=True)
def _clean_browser_rollout_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BROWSER_USE_AUTO_MOUNT_ENABLED",
        "BROWSER_USE_LOCAL_ENABLED",
        "BROWSER_USE_CLOUD_ENABLED",
        "BROWSER_USE_WRITE_ACTION_ENABLED",
        "BROWSER_USE_TENANT_ALLOWLIST",
        "BROWSER_USE_USER_ALLOWLIST",
        "BROWSER_USE_TRAFFIC_PERCENT",
        "BROWSER_USE_SHADOW_PLANNER_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("text", "location", "reason"),
    [
        ("打开 https://example.com 告诉我网页标题", "cloud", "PUBLIC_WEB_TASK"),
        ("去官网看看今天的价格", "cloud", "PUBLIC_WEB_TASK"),
        ("读取我当前 Chrome 标签页", "local", "LOCAL_BROWSER_STATE"),
        ("看看 localhost:5173 页面是否正常", "local", "LOCAL_BROWSER_STATE"),
    ],
)
def test_auto_policy_mounts_browser_for_web_interaction(
    text: str,
    location: str,
    reason: str,
) -> None:
    resolved = resolve_run_tool_plan(_payload(text), _registry())

    assert resolved.selected_tool_ids == ("browser_use",)
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "mount"
    assert resolved.browser_plan.browser_location == location
    assert resolved.browser_plan.reason_code == reason


@pytest.mark.parametrize(
    "text",
    [
        "解释浏览器同源策略",
        "写一个 Browser Use 的单元测试",
        "把这段浏览器报错翻译成英文",
        "请润色这段产品说明",
    ],
)
def test_auto_policy_does_not_mount_for_browser_discussion(text: str) -> None:
    resolved = resolve_run_tool_plan(_payload(text), _registry())

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "no_tool"


def test_auto_policy_merges_only_manual_tools_with_automatic_plan() -> None:
    resolved = resolve_run_tool_plan(
        _payload(
            "打开 example.com",
            manual_tools=["current_time"],
        ),
        _registry(),
    )

    assert resolved.selected_tool_ids == ("current_time", "browser_use")


@pytest.mark.parametrize(
    "text",
    [
        "打开后台页面，填写公告但不要发布",
        "编辑网页表单，不要点击提交",
        "Open the website, fill the form, but do not submit it",
        "Update the online draft without publishing it",
    ],
)
def test_prepare_intent_ignores_negated_commit_verbs(text: str) -> None:
    resolved = resolve_run_tool_plan(_payload(text), _registry())

    assert resolved.selected_tool_ids == ("browser_use",)
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.risk_level == "write_prepare"
    assert resolved.browser_plan.approval == "not_required"


def test_affirmative_commit_remains_high_risk_after_a_negated_action() -> None:
    resolved = resolve_run_tool_plan(
        _payload("不要删除旧公告，发布网页上的新公告"),
        _registry(),
    )

    assert resolved.browser_plan is not None
    assert resolved.browser_plan.risk_level == "high"
    assert resolved.browser_plan.approval == "required"


def test_automatic_tool_cannot_be_requested_as_a_manual_tool() -> None:
    with pytest.raises(ToolPolicyError, match="automatic.*browser_use"):
        resolve_run_tool_plan(
            _payload("hello", manual_tools=["browser_use"]),
            _registry(),
        )


def test_tool_policy_and_legacy_platform_tools_are_mutually_exclusive() -> None:
    payload = _payload("打开 example.com")
    payload["platform_tools"] = ["current_time"]

    with pytest.raises(ToolPolicyError, match="cannot be used together"):
        resolve_run_tool_plan(payload, _registry())


def test_manual_only_and_off_never_auto_mount_browser() -> None:
    manual_only = _payload(
        "打开 example.com",
        mode="manual_only",
        manual_tools=["current_time"],
    )
    off = _payload("打开 example.com", mode="off")

    assert resolve_run_tool_plan(manual_only, _registry()).selected_tool_ids == (
        "current_time",
    )
    assert resolve_run_tool_plan(off, _registry()).selected_tool_ids == ()


def test_explicit_opt_out_wins_over_browser_intent() -> None:
    resolved = resolve_run_tool_plan(
        _payload("不要使用浏览器，直接解释 https://example.com 这个 URL"),
        _registry(),
    )

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.reason_code == "USER_DISABLED"


def test_suppressed_browser_tool_is_not_mounted() -> None:
    resolved = resolve_run_tool_plan(
        _payload("打开 example.com", suppressed_tools=["browser_use"]),
        _registry(),
    )

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.reason_code == "TOOL_SUPPRESSED"


def test_browser_location_override_is_trusted_policy_not_model_argument() -> None:
    resolved = resolve_run_tool_plan(
        _payload("打开 example.com", browser_location_override="local"),
        _registry(),
    )

    assert resolved.browser_plan is not None
    assert resolved.browser_plan.browser_location == "local"


def test_public_tool_plan_event_excludes_executor_identity_and_approval_token() -> None:
    resolved = resolve_run_tool_plan(
        _payload(
            "确认执行",
            browser_location_override="cloud",
            approval_id="opaque-approval-token",
        ),
        _registry(),
    )

    encoded = studio_tool_plan_sse_event(resolved.browser_plan)

    assert encoded is not None
    assert encoded.startswith(b"data: ")
    assert b"opaque-approval-token" not in encoded
    assert b"plan_id" not in encoded
    assert b"endpoint" not in encoded
    assert b"context" not in encoded
    assert b'"studioEvent":"studio.tool_plan"' in encoded


def test_approval_commit_forces_same_location_browser_mount() -> None:
    resolved = resolve_run_tool_plan(
        _payload(
            "确认执行",
            browser_location_override="local",
            approval_id="opaque-approval-token",
        ),
        _registry(),
    )

    assert resolved.selected_tool_ids == ("browser_use",)
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "mount"
    assert resolved.browser_plan.browser_location == "local"
    assert resolved.browser_plan.risk_level == "high"
    assert resolved.browser_plan.approval == "approved"
    assert resolved.browser_plan.reason_code == "BROWSER_APPROVAL_COMMIT"


@pytest.mark.parametrize(
    "overrides",
    [
        {"browser_location_override": None},
        {"browser_location_override": "cloud", "mode": "manual_only"},
        {
            "browser_location_override": "cloud",
            "suppressed_tools": ["browser_use"],
        },
    ],
)
def test_approval_commit_rejects_ambiguous_or_disabled_policy(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ToolPolicyError, match="approval_id"):
        resolve_run_tool_plan(
            _payload(
                "确认执行",
                approval_id="opaque-approval-token",
                **overrides,
            ),
            _registry(),
        )


@pytest.mark.parametrize("text", ["填写公告内容", "发布公告"])
def test_write_action_switch_fails_closed_before_mount(
    text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_WRITE_ACTION_ENABLED", "0")

    resolved = resolve_run_tool_plan(_payload(text + " 到官网"), _registry())

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "unavailable"
    assert resolved.browser_plan.reason_code == "WRITE_ACTION_DISABLED"


def test_write_action_switch_rejects_pending_approval_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_WRITE_ACTION_ENABLED", "false")

    resolved = resolve_run_tool_plan(
        _payload(
            "确认执行",
            browser_location_override="cloud",
            approval_id="opaque-approval-token",
        ),
        _registry(),
    )

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.reason_code == "WRITE_ACTION_DISABLED"


@pytest.mark.parametrize(
    ("switch", "text", "reason"),
    [
        (
            "BROWSER_USE_AUTO_MOUNT_ENABLED",
            "打开 example.com 告诉我标题",
            "BROWSER_USE_DISABLED",
        ),
        (
            "BROWSER_USE_CLOUD_ENABLED",
            "打开 example.com 告诉我标题",
            "CLOUD_DISABLED",
        ),
        (
            "BROWSER_USE_LOCAL_ENABLED",
            "读取我当前 Chrome 标签页",
            "LOCAL_DISABLED",
        ),
    ],
)
def test_browser_kill_switches_remove_tool_from_new_run_catalog(
    switch: str,
    text: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(switch, "0")

    resolved = resolve_run_tool_plan(_payload(text), _registry())

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "unavailable"
    assert resolved.browser_plan.platform_tools == ()
    assert resolved.browser_plan.reason_code == reason


def test_tenant_and_user_allowlists_use_only_trusted_rollout_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.setenv("BROWSER_USE_USER_ALLOWLIST", "alice@example.com")
    payload = _payload("打开 example.com")
    payload["tenant_id"] = "tenant-a"
    payload["owner_id"] = "alice@example.com"

    denied = resolve_run_tool_plan(payload, _registry())
    allowed = resolve_run_tool_plan(
        payload,
        _registry(),
        rollout_context=BrowserRolloutContext(
            tenant_id="tenant-a",
            user_identifiers=("alice@example.com", "user-123"),
            rollout_key="tenant-a:user-123:session-1",
        ),
    )

    assert denied.selected_tool_ids == ()
    assert denied.browser_plan is not None
    assert denied.browser_plan.reason_code == "ROLLOUT_NOT_ELIGIBLE"
    assert allowed.selected_tool_ids == ("browser_use",)


def test_traffic_rollout_is_stable_and_zero_percent_never_mounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_TRAFFIC_PERCENT", "0")
    context = BrowserRolloutContext(
        tenant_id="tenant-a",
        user_identifiers=("user-1",),
        rollout_key="tenant-a:user-1:session-1",
    )

    first = resolve_run_tool_plan(
        _payload("打开 example.com"),
        _registry(),
        rollout_context=context,
    )
    second = resolve_run_tool_plan(
        _payload("打开 example.com"),
        _registry(),
        rollout_context=context,
    )

    assert first.selected_tool_ids == second.selected_tool_ids == ()
    assert first.browser_plan is not None
    assert second.browser_plan is not None
    assert first.browser_plan.reason_code == "ROLLOUT_NOT_ELIGIBLE"
    assert second.browser_plan.reason_code == "ROLLOUT_NOT_ELIGIBLE"


def test_invalid_traffic_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_TRAFFIC_PERCENT", "not-a-number")

    resolved = resolve_run_tool_plan(
        _payload("打开 example.com"),
        _registry(),
        rollout_context=BrowserRolloutContext(rollout_key="stable-run"),
    )

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.reason_code == "ROLLOUT_CONFIG_INVALID"


def test_shadow_planner_records_candidate_without_mounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSER_USE_AUTO_MOUNT_ENABLED", "0")
    monkeypatch.setenv("BROWSER_USE_SHADOW_PLANNER_ENABLED", "1")

    resolved = resolve_run_tool_plan(
        _payload("打开 example.com 告诉我标题"),
        _registry(),
        rollout_context=BrowserRolloutContext(rollout_key="shadow-run"),
    )

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "no_tool"
    assert resolved.browser_plan.reason_code == "SHADOW_PLANNER"
    assert resolved.browser_plan.browser_location == "cloud"
    assert resolved.browser_plan.risk_level == "read_only"


def test_legacy_static_browser_agent_never_gets_dynamic_browser_tool() -> None:
    resolved = resolve_run_tool_plan(
        _payload("打开 example.com"),
        _registry(),
        rollout_context=BrowserRolloutContext(
            legacy_static_browser=True,
            rollout_key="legacy-runtime",
        ),
    )

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "no_tool"
    assert resolved.browser_plan.reason_code == "LEGACY_STATIC_BROWSER_AGENT"


@pytest.mark.parametrize(
    "runtime",
    [
        SimpleNamespace(
            tags=[SimpleNamespace(key="veadk:browser-use-mode", value="legacy_static")],
            envs=[],
        ),
        SimpleNamespace(
            tags=[],
            envs=[
                SimpleNamespace(
                    key="JANUS_BROWSER_GATEWAY_URL",
                    value="must-not-be-read",
                )
            ],
        ),
    ],
)
def test_legacy_runtime_detection_uses_marker_or_environment_key(
    runtime: object,
) -> None:
    assert runtime_has_legacy_static_browser(runtime)


def test_dynamic_runtime_is_not_misclassified_as_legacy() -> None:
    runtime = SimpleNamespace(
        tags=[SimpleNamespace(key="veadk:browser-use-mode", value="dynamic_run_tool")],
        envs=[SimpleNamespace(key="UNRELATED", value="anything")],
    )

    assert not runtime_has_legacy_static_browser(runtime)


def test_runtime_without_tool_host_capability_cannot_publish_browser_tool() -> None:
    resolved = resolve_run_tool_plan(
        _payload("打开 example.com"),
        _registry(),
        rollout_context=BrowserRolloutContext(
            runtime_tool_host_capability=False,
            rollout_key="runtime-without-capability",
        ),
    )

    assert resolved.selected_tool_ids == ()
    assert resolved.browser_plan is not None
    assert resolved.browser_plan.decision == "unavailable"
    assert resolved.browser_plan.reason_code == "RUNTIME_TOOL_HOST_UNAVAILABLE"
