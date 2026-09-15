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

"""Model-input governance for tools removed from a Studio run catalog."""

from __future__ import annotations

import logging
import threading
from collections.abc import Collection, Sequence
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

logger = logging.getLogger(__name__)

_INTERNAL_TOOL_NAMES = frozenset({"exit_loop", "transfer_to_agent"})
_UNAVAILABLE_REASON_CODE = "TOOL_NOT_AVAILABLE_IN_CURRENT_RUN"
_UNAVAILABLE_MESSAGE = (
    "This tool is not available in the current run. Continue without it, "
    "or ask the user to start a new run that enables the capability."
)
_STALE_CALL_SUMMARY = (
    "A historical tool call was omitted because that tool is not available "
    "in this run. Do not retry it in this run."
)
_STALE_RESPONSE_SUMMARY = (
    "A historical tool response was omitted because that tool is not available "
    "in this run."
)


def _part_tool_name(part: types.Part) -> tuple[str | None, str | None]:
    if part.function_call is not None:
        return part.function_call.name, "call"
    if part.function_response is not None:
        return part.function_response.name, "response"
    return None, None


def project_available_tool_history(
    contents: Sequence[types.Content],
    *,
    available_tool_names: Collection[str],
) -> list[types.Content]:
    """Return an LLM-only projection without unavailable historical tool parts."""

    available = {*available_tool_names, *_INTERNAL_TOOL_NAMES}
    projected = [content.model_copy(deep=True) for content in contents]
    changed = False

    for content in projected:
        replacement_parts: list[types.Part] = []
        for part in content.parts or []:
            tool_name, part_kind = _part_tool_name(part)
            if not tool_name or tool_name in available:
                replacement_parts.append(part)
                continue
            changed = True
            summary = (
                _STALE_CALL_SUMMARY if part_kind == "call" else _STALE_RESPONSE_SUMMARY
            )
            replacement_parts.append(types.Part(text=summary))
        content.parts = replacement_parts

    return projected if changed else list(contents)


class StudioToolHistoryPlugin(BasePlugin):
    """Keep stale Studio tool history from breaking a later immutable catalog."""

    def __init__(self) -> None:
        super().__init__(name="veadk_studio_tool_history")
        self._recovered_tools: dict[str, set[str]] = {}
        self._recovery_lock = threading.Lock()

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> None:
        del callback_context
        llm_request.contents = project_available_tool_history(
            llm_request.contents,
            available_tool_names=llm_request.tools_dict,
        )
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> dict[str, str] | None:
        del tool_args
        if not self._is_unknown_tool_error(tool, error):
            return None

        invocation_id = str(getattr(tool_context, "invocation_id", "") or "")
        tool_name = str(getattr(tool, "name", "") or "")
        if not invocation_id or not tool_name:
            return None

        with self._recovery_lock:
            recovered = self._recovered_tools.setdefault(invocation_id, set())
            if tool_name in recovered:
                return None
            recovered.add(tool_name)

        if tool_name == "browser_use":
            logger.info(
                "browser_use_event",
                extra={
                    "browser_event": "browser_unknown_tool_recovered",
                    "reason_code": _UNAVAILABLE_REASON_CODE,
                    "runtime_capability": "studio_tool_host",
                    "location": "none",
                    "risk": "none",
                    "latency_ms": 0.0,
                    "error_class": "UnknownTool",
                    "catalog_revision": "current_run",
                    "legacy_agent": False,
                },
            )

        return {
            "status": "unavailable",
            "reason_code": _UNAVAILABLE_REASON_CODE,
            "message": _UNAVAILABLE_MESSAGE,
        }

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        invocation_id = str(getattr(invocation_context, "invocation_id", "") or "")
        if invocation_id:
            with self._recovery_lock:
                self._recovered_tools.pop(invocation_id, None)

    @staticmethod
    def _is_unknown_tool_error(tool: BaseTool, error: Exception) -> bool:
        return (
            isinstance(error, ValueError)
            and getattr(tool, "description", None) == "Tool not found"
            and str(error).startswith("Tool '")
            and "' not found.\nAvailable tools:" in str(error)
        )
