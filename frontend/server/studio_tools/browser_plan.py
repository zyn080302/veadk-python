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

"""Trusted per-run Browser Use intent and Studio Tool policy planning."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal
from uuid import uuid4

from frontend.server.studio_tools.registry import StudioToolRegistry

ToolPolicyMode = Literal["auto", "manual_only", "off"]
BrowserLocation = Literal["local", "cloud"]
BrowserDecision = Literal["mount", "no_tool", "unavailable"]

_POLICY_KEYS = frozenset(
    {
        "mode",
        "manual_tools",
        "suppressed_tools",
        "browser_location_override",
        "approval_id",
    }
)
_DOMAIN_RE = re.compile(
    r"(?i)(?:https?://|www\.)[^\s]+|\b[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?::\d+)?(?:/[^\s]*)?"
)
_LOCAL_RE = re.compile(
    r"(?i)\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?\b|"
    r"当前(?:的)?\s*(?:chrome|浏览器)?\s*标签页|本地浏览器|我打开的系统|"
    r"current\s+(?:chrome\s+)?tab|my\s+(?:open\s+)?browser"
)
_OPT_OUT_RE = re.compile(
    r"(?i)不要(?:使用|调用|打开)?(?:任何)?浏览器|不用浏览器|禁止(?:使用)?浏览器|"
    r"do\s+not\s+use\s+(?:the\s+)?browser|without\s+(?:using\s+)?(?:a\s+)?browser"
)
_DISCUSSION_RE = re.compile(
    r"(?i)(?:解释|说明|介绍|原理|概念).{0,16}(?:浏览器|browser)|"
    r"(?:浏览器|browser\s*use).{0,20}(?:单元测试|测试代码|源码|原理|同源策略)|"
    r"(?:写|生成|实现).{0,16}(?:browser\s*use|浏览器).{0,16}(?:测试|代码)|"
    r"(?:翻译|润色|改写).{0,24}(?:浏览器|browser)|"
    r"browser\s+(?:architecture|api|error|test|unit\s+test)"
)
_PUBLIC_ACTION_RE = re.compile(
    r"(?i)(?:打开|访问|进入|去|看看|浏览|查看|读取|抓取|采集|搜索|查找|对比|比较|"
    r"填写|点击|下载|上传|登录|提交|发布|发送|删除|购买|下单|"
    r"open|visit|browse|navigate|go\s+to|look\s+up|search|find|compare|"
    r"click|fill|download|upload|sign\s+in|submit|publish|send|delete|buy)"
)
_WEB_TARGET_RE = re.compile(
    r"(?i)(?:官网|网页|网站|页面|站点|链接|商品|供应商|在线|web\s*site|"
    r"website|webpage|page|site|online)"
)
_HIGH_RISK_RE = re.compile(
    r"(?i)(?:提交|发布|发送|删除|购买|下单|付款|确认支付|"
    r"submit|publish|send|delete|purchase|buy|pay|place\s+(?:the\s+)?order)"
)
_NEGATED_HIGH_RISK_RE = re.compile(
    r"(?i)(?:不要|别|禁止|无需|不必|不可|不能|不应|不准|不)"
    r"\s*(?:(?:再|去|执行|进行|点击|确认)\s*){0,2}"
    r"(?:提交|发布|发送|删除|购买|下单|付款|确认支付)|"
    r"(?:do\s+not|don['’]t|never)\s+(?:\w+\s+){0,2}"
    r"(?:submit|publish|send|delete|purchase|buy|pay|place\s+(?:the\s+)?order)|"
    r"without\s+(?:\w+\s+){0,2}"
    r"(?:submitting|publishing|sending|deleting|purchasing|buying|paying|"
    r"placing\s+(?:the\s+)?order)"
)
_PREPARE_RE = re.compile(
    r"(?i)(?:填写|填入|上传|编辑|修改|勾选|fill|upload|edit|change|select|"
    r"(?:update|revise)\s+(?:the\s+|an?\s+)?"
    r"(?:(?:online|existing|new|current)\s+)?"
    r"(?:draft|form|field|post|announcement|content))"
)
_LEGACY_BROWSER_ENV_KEYS = frozenset(
    {"JANUS_BROWSER_GATEWAY_URL", "JANUS_BROWSER_GATEWAY_TOKEN"}
)
_BROWSER_MODE_TAG = "veadk:browser-use-mode"


class ToolPolicyError(ValueError):
    """The Studio-private Tool policy is invalid or ambiguous."""


@dataclass(frozen=True)
class BrowserRolloutContext:
    """Trusted identity and Runtime facts used only for Browser Use rollout."""

    tenant_id: str = ""
    user_identifiers: tuple[str, ...] = ()
    rollout_key: str = ""
    legacy_static_browser: bool = False
    runtime_tool_host_capability: bool | None = None


@dataclass(frozen=True)
class BrowserToolPlan:
    plan_id: str
    decision: BrowserDecision
    platform_tools: tuple[str, ...]
    intent_class: str
    browser_location: BrowserLocation | None
    risk_level: str
    approval: str
    reason_code: str
    context_policy: str
    approval_id: str | None = None

    def execution_metadata(self) -> Mapping[str, Any]:
        """Return the immutable, server-derived subset needed by an executor."""

        return asdict(self)

    def public_event_payload(self) -> dict[str, str | None]:
        """Return the bounded, non-sensitive projection exposed to Studio UI."""

        return {
            "decision": self.decision,
            "reasonCode": self.reason_code,
            "browserLocation": self.browser_location,
            "riskLevel": self.risk_level,
            "approval": self.approval,
        }


@dataclass(frozen=True)
class ResolvedRunToolPlan:
    selected_tool_ids: tuple[str, ...]
    browser_plan: BrowserToolPlan | None = None


@dataclass(frozen=True)
class _ToolPolicy:
    mode: ToolPolicyMode
    manual_tools: tuple[str, ...]
    suppressed_tools: tuple[str, ...]
    browser_location_override: BrowserLocation | None
    approval_id: str | None


def _string_ids(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ToolPolicyError(
            f"tool_policy.{field_name} must be a list of non-empty tool IDs"
        )
    return tuple(dict.fromkeys(item.strip() for item in value))


def _parse_policy(value: object, registry: StudioToolRegistry) -> _ToolPolicy:
    if not isinstance(value, Mapping):
        raise ToolPolicyError("tool_policy must be an object")
    unknown_keys = sorted(set(value) - _POLICY_KEYS)
    if unknown_keys:
        raise ToolPolicyError("unknown tool_policy fields: " + ", ".join(unknown_keys))
    mode = value.get("mode", "auto")
    if mode not in {"auto", "manual_only", "off"}:
        raise ToolPolicyError("tool_policy.mode must be auto, manual_only, or off")
    manual_tools = _string_ids(value.get("manual_tools"), "manual_tools")
    suppressed_tools = _string_ids(value.get("suppressed_tools"), "suppressed_tools")
    for name in (*manual_tools, *suppressed_tools):
        if not registry.has_tool(name):
            raise ToolPolicyError(f"Unknown Studio tools: {name}")
    automatic_manual = [
        name for name in manual_tools if registry.activation_mode(name) == "automatic"
    ]
    if automatic_manual:
        raise ToolPolicyError(
            "automatic Studio tools cannot be selected through manual_tools: "
            + ", ".join(automatic_manual)
        )
    non_automatic_suppressed = [
        name
        for name in suppressed_tools
        if registry.activation_mode(name) != "automatic"
    ]
    if non_automatic_suppressed:
        raise ToolPolicyError(
            "suppressed_tools only accepts automatic Studio tools: "
            + ", ".join(non_automatic_suppressed)
        )
    location = value.get("browser_location_override")
    if location not in {None, "local", "cloud"}:
        raise ToolPolicyError(
            "tool_policy.browser_location_override must be local, cloud, or null"
        )
    approval_id = value.get("approval_id")
    if approval_id is not None and (
        not isinstance(approval_id, str)
        or not approval_id.strip()
        or len(approval_id) > 512
    ):
        raise ToolPolicyError(
            "tool_policy.approval_id must be a non-empty opaque string"
        )
    if approval_id is not None and mode != "auto":
        raise ToolPolicyError("tool_policy.approval_id requires mode=auto")
    if approval_id is not None and location is None:
        raise ToolPolicyError(
            "tool_policy.approval_id requires a browser_location_override"
        )
    if approval_id is not None and "browser_use" in suppressed_tools:
        raise ToolPolicyError("tool_policy.approval_id cannot suppress browser_use")
    if mode == "off" and (manual_tools or approval_id is not None):
        raise ToolPolicyError("tool_policy.mode=off cannot select tools or approvals")
    return _ToolPolicy(
        mode=mode,  # type: ignore[arg-type]
        manual_tools=manual_tools,
        suppressed_tools=suppressed_tools,
        browser_location_override=location,  # type: ignore[arg-type]
        approval_id=approval_id.strip() if isinstance(approval_id, str) else None,
    )


def _message_text(payload: Mapping[str, Any]) -> str:
    message = payload.get("new_message")
    if not isinstance(message, Mapping):
        raise ToolPolicyError("run_sse new_message must be an object")
    parts = message.get("parts")
    if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes)):
        raise ToolPolicyError("run_sse new_message.parts must be a list")
    return "\n".join(
        str(part.get("text"))
        for part in parts
        if isinstance(part, Mapping) and isinstance(part.get("text"), str)
    ).strip()


def _enabled(name: str) -> bool:
    return os.getenv(name, "1").strip().lower() not in {"0", "false", "off", "no"}


def _record_key(record: object) -> str:
    if isinstance(record, Mapping):
        return str(record.get("key") or record.get("Key") or "").strip()
    return str(
        getattr(record, "key", None) or getattr(record, "Key", None) or ""
    ).strip()


def _record_value(record: object) -> str:
    if isinstance(record, Mapping):
        return str(record.get("value") or record.get("Value") or "").strip()
    return str(
        getattr(record, "value", None) or getattr(record, "Value", None) or ""
    ).strip()


def runtime_has_legacy_static_browser(runtime: object) -> bool:
    """Detect a deployed static Janus Agent without reading environment values."""

    envs = getattr(runtime, "envs", None) or ()
    if any(_record_key(item) in _LEGACY_BROWSER_ENV_KEYS for item in envs):
        return True
    tags = getattr(runtime, "tags", None) or ()
    return any(
        _record_key(item) == _BROWSER_MODE_TAG
        and _record_value(item).casefold() == "legacy_static"
        for item in tags
    )


def _configured_allowlist(name: str) -> frozenset[str] | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return frozenset(item.strip().casefold() for item in raw.split(",") if item.strip())


def _allowlisted(allowlist: frozenset[str] | None, values: Sequence[str]) -> bool:
    if allowlist is None:
        return True
    if "*" in allowlist:
        return True
    normalized = {value.strip().casefold() for value in values if value.strip()}
    return bool(normalized.intersection(allowlist))


def _rollout_eligibility(context: BrowserRolloutContext) -> tuple[bool, str]:
    tenant_allowlist = _configured_allowlist("BROWSER_USE_TENANT_ALLOWLIST")
    user_allowlist = _configured_allowlist("BROWSER_USE_USER_ALLOWLIST")
    if not _allowlisted(tenant_allowlist, (context.tenant_id,)) or not _allowlisted(
        user_allowlist,
        context.user_identifiers,
    ):
        return False, "ROLLOUT_NOT_ELIGIBLE"

    raw_percent = os.getenv("BROWSER_USE_TRAFFIC_PERCENT", "100").strip()
    try:
        percent = float(raw_percent)
    except ValueError:
        return False, "ROLLOUT_CONFIG_INVALID"
    if not math.isfinite(percent) or not 0 <= percent <= 100:
        return False, "ROLLOUT_CONFIG_INVALID"
    if percent >= 100:
        return True, "ROLLOUT_ELIGIBLE"
    if percent <= 0:
        return False, "ROLLOUT_NOT_ELIGIBLE"
    if not context.rollout_key:
        return False, "ROLLOUT_CONFIG_INVALID"
    digest = hashlib.sha256(context.rollout_key.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 10_000
    return (
        (True, "ROLLOUT_ELIGIBLE")
        if bucket < round(percent * 100)
        else (False, "ROLLOUT_NOT_ELIGIBLE")
    )


def _browser_intent(text: str) -> tuple[bool, BrowserLocation | None, str]:
    if _OPT_OUT_RE.search(text):
        return False, None, "USER_DISABLED"
    if _DISCUSSION_RE.search(text):
        return False, None, "NON_INTERACTIVE_BROWSER_DISCUSSION"
    if _LOCAL_RE.search(text):
        return True, "local", "LOCAL_BROWSER_STATE"
    has_target = bool(_DOMAIN_RE.search(text) or _WEB_TARGET_RE.search(text))
    if has_target and _PUBLIC_ACTION_RE.search(text):
        return True, "cloud", "PUBLIC_WEB_TASK"
    return False, None, "NO_BROWSER_INTENT"


def _risk(text: str) -> tuple[str, str]:
    affirmative_text = _NEGATED_HIGH_RISK_RE.sub("", text)
    if _HIGH_RISK_RE.search(affirmative_text):
        return "high", "required"
    if _PREPARE_RE.search(text):
        return "write_prepare", "not_required"
    return "read_only", "not_required"


def _no_browser_plan(reason_code: str) -> BrowserToolPlan:
    return BrowserToolPlan(
        plan_id=uuid4().hex,
        decision="no_tool",
        platform_tools=(),
        intent_class="none",
        browser_location=None,
        risk_level="none",
        approval="not_required",
        reason_code=reason_code,
        context_policy="none",
    )


def _candidate_plan(
    *,
    decision: BrowserDecision,
    reason_code: str,
    location: BrowserLocation,
    risk_level: str,
    approval: str,
) -> BrowserToolPlan:
    return BrowserToolPlan(
        plan_id=uuid4().hex,
        decision=decision,
        platform_tools=(),
        intent_class="web_interaction",
        browser_location=location,
        risk_level=risk_level,
        approval=approval,
        reason_code=reason_code,
        context_policy="none",
    )


def resolve_run_tool_plan(
    payload: Mapping[str, Any],
    registry: StudioToolRegistry,
    *,
    rollout_context: BrowserRolloutContext | None = None,
) -> ResolvedRunToolPlan:
    """Resolve one immutable Tool selection from Studio-private request policy."""

    if "tool_policy" not in payload:
        if "platform_tools" not in payload:
            return ResolvedRunToolPlan(selected_tool_ids=())
        raw_tools = payload["platform_tools"]
        selected = _string_ids(raw_tools, "platform_tools")
        return ResolvedRunToolPlan(selected_tool_ids=selected)
    if "platform_tools" in payload:
        raise ToolPolicyError("tool_policy and platform_tools cannot be used together")
    policy = _parse_policy(payload["tool_policy"], registry)
    manual = policy.manual_tools if policy.mode != "off" else ()
    if policy.mode != "auto":
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_no_browser_plan("AUTO_POLICY_DISABLED"),
        )

    text = _message_text(payload)
    if policy.approval_id is not None:
        should_mount = True
        location = policy.browser_location_override
        reason = "BROWSER_APPROVAL_COMMIT"
    else:
        should_mount, location, reason = _browser_intent(text)
    if not should_mount:
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_no_browser_plan(reason),
        )
    if "browser_use" in policy.suppressed_tools:
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_no_browser_plan("TOOL_SUPPRESSED"),
        )
    context = rollout_context or BrowserRolloutContext()
    if context.legacy_static_browser:
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_no_browser_plan("LEGACY_STATIC_BROWSER_AGENT"),
        )
    eligible, rollout_reason = _rollout_eligibility(context)
    if not eligible:
        if rollout_reason == "ROLLOUT_CONFIG_INVALID":
            decision: BrowserDecision = "unavailable"
        else:
            decision = "no_tool"
        location = policy.browser_location_override or location or "cloud"
        risk_level, approval = (
            ("high", "approved") if policy.approval_id is not None else _risk(text)
        )
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_candidate_plan(
                decision=decision,
                reason_code=rollout_reason,
                location=location,
                risk_level=risk_level,
                approval=approval,
            ),
        )
    location = policy.browser_location_override or location or "cloud"
    if policy.approval_id is not None:
        risk_level, approval = "high", "approved"
    else:
        risk_level, approval = _risk(text)
    if context.runtime_tool_host_capability is False:
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_candidate_plan(
                decision="unavailable",
                reason_code="RUNTIME_TOOL_HOST_UNAVAILABLE",
                location=location,
                risk_level=risk_level,
                approval=approval,
            ),
        )
    if (
        _enabled("BROWSER_USE_SHADOW_PLANNER_ENABLED")
        and os.getenv("BROWSER_USE_SHADOW_PLANNER_ENABLED") is not None
    ):
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_candidate_plan(
                decision="no_tool",
                reason_code="SHADOW_PLANNER",
                location=location,
                risk_level=risk_level,
                approval=approval,
            ),
        )
    if not registry.has_tool("browser_use") or not _enabled(
        "BROWSER_USE_AUTO_MOUNT_ENABLED"
    ):
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_candidate_plan(
                decision="unavailable",
                reason_code="BROWSER_USE_DISABLED",
                location=location,
                risk_level=risk_level,
                approval=approval,
            ),
        )
    location_flag = (
        "BROWSER_USE_LOCAL_ENABLED"
        if location == "local"
        else "BROWSER_USE_CLOUD_ENABLED"
    )
    if not _enabled(location_flag):
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_candidate_plan(
                decision="unavailable",
                reason_code=f"{location.upper()}_DISABLED",
                location=location,
                risk_level=risk_level,
                approval=approval,
            ),
        )
    if risk_level != "read_only" and not _enabled("BROWSER_USE_WRITE_ACTION_ENABLED"):
        return ResolvedRunToolPlan(
            selected_tool_ids=manual,
            browser_plan=_candidate_plan(
                decision="unavailable",
                reason_code="WRITE_ACTION_DISABLED",
                location=location,
                risk_level=risk_level,
                approval=approval,
            ),
        )
    selected = tuple(dict.fromkeys((*manual, "browser_use")))
    plan = BrowserToolPlan(
        plan_id=uuid4().hex,
        decision="mount",
        platform_tools=("browser_use",),
        intent_class="web_interaction",
        browser_location=location,
        risk_level=risk_level,
        approval=approval,
        reason_code=reason,
        context_policy="new_or_resume_same_location",
        approval_id=policy.approval_id,
    )
    return ResolvedRunToolPlan(selected_tool_ids=selected, browser_plan=plan)


def studio_tool_plan_sse_event(plan: BrowserToolPlan | None) -> bytes | None:
    """Encode the Studio-private ToolPlan event without executor-only fields."""

    if plan is None:
        return None
    event = {
        "studioEvent": "studio.tool_plan",
        "payload": plan.public_event_payload(),
    }
    return (
        "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"
    ).encode("utf-8")


__all__ = [
    "BrowserRolloutContext",
    "BrowserToolPlan",
    "ResolvedRunToolPlan",
    "ToolPolicyError",
    "resolve_run_tool_plan",
    "runtime_has_legacy_static_browser",
    "studio_tool_plan_sse_event",
]
