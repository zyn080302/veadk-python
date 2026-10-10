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

"""Programmatic provider contexts for the existing native Codex runtime.

Adapters own transport resources only. Codex retains its tool loop and history.
Factories never appear in serialized configuration or Studio drafts.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


Executor = Callable[[dict[str, Any], str], Awaitable[str]]


@dataclass(frozen=True)
class CodexProviderEndpoint:
    """An invocation-scoped Responses endpoint, returned by a trusted factory."""

    api_base: str
    api_key: str = field(repr=False)
    handles_extra_body: bool = False
    wrap_tool_executor: Callable[[str, Executor], Executor] | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        try:
            parsed = urlsplit(self.api_base)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and "?" not in self.api_base
                and "#" not in self.api_base
                and not any(ord(c) <= 32 or ord(c) == 127 for c in self.api_base)
                and parsed.port != 0
                and isinstance(self.api_key, str)
                and bool(self.api_key)
                and not any(c in self.api_key for c in "\r\n\0")
            )
        except (TypeError, ValueError):
            valid = False
        if self.wrap_tool_executor is not None and not callable(
            self.wrap_tool_executor
        ):
            valid = False
        if not valid:
            raise ValueError("Invalid Codex provider endpoint or credential")


def wrap_provider_executors(
    endpoint: CodexProviderEndpoint | None, executors: dict[str, Executor]
) -> dict[str, Executor]:
    """Decorate registered executors without changing schemas or admission."""
    if endpoint is None or endpoint.wrap_tool_executor is None:
        return executors
    wrapped = {}
    for name, executor in executors.items():
        decorated = endpoint.wrap_tool_executor(name, executor)
        if not callable(decorated):
            raise TypeError("Provider must return a callable tool executor")
        wrapped[name] = decorated
    return wrapped
