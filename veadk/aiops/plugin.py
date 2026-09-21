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

"""Domain extension contracts using ordinary veADK tools and callbacks."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veadk.aiops.config import AgentConfig


@dataclass(frozen=True)
class BuildContext:
    config: AgentConfig
    sidecar_env: Mapping[str, str] = field(default_factory=dict, repr=False)
    environ: Mapping[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class AgentPlugin:
    """Inject domain assets; factories create fresh tools for every Agent.

    Use standard veADK/ADK functions, BaseTool and BaseToolset objects. Stateful
    tools must be returned by a factory instead of sharing instances across
    agents. ``configure_agent`` attaches domain callbacks, such as report URLs.
    ``adk_plugins`` are native Google ADK plugins preserved on the App.
    """

    name: str
    instruction: str = ""
    skill_directories: tuple[Path, ...] = ()
    tools_factory: Callable[[BuildContext], Sequence[Any]] | None = None
    mcp_factory: Callable[[BuildContext], Sequence[Any]] | None = None
    configure_agent: Callable[[Any], None] | None = None
    adk_plugins_factory: Callable[[], Sequence[Any]] | None = None
    exclusive_tool_names: frozenset[str] = frozenset()
    closeout_tool_names: frozenset[str] = frozenset()
    parallel_description: str | None = None
    parallel_parameter_descriptions: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("plugin name must not be empty")


__all__ = ["AgentPlugin", "BuildContext"]
