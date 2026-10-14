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

"""Explicit AI OPS composition without importing Core for ordinary Agents."""

from __future__ import annotations

from collections.abc import Sequence
import re
from typing import Any

from veadk.extensions.aiops.backend import AIOpsBackend, resolve_backend
from veadk.extensions.aiops.config import AgentConfig
from veadk.extensions.aiops.plugin import AgentPlugin


class AIOpsExtension:
    """Opt a fresh Agent into an optional operational backend.

    Construction does not load Core, start services or change the environment.
    Provider resources belong to each native runtime invocation; the extension
    itself has no process lifecycle to close.
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        plugins: Sequence[AgentPlugin] = (),
        *,
        enabled: bool = True,
        backend: str = "agentkit",
    ) -> None:
        if not isinstance(backend, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", backend):
            raise ValueError("backend must be an installed entry-point name")
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        if config is not None and not isinstance(config, AgentConfig):
            raise TypeError("config must be AgentConfig")
        self.config = config if config is not None else AgentConfig()
        self.plugins = tuple(plugins)
        if not all(isinstance(plugin, AgentPlugin) for plugin in self.plugins):
            raise TypeError("plugins must contain AgentPlugin objects")
        self.enabled = enabled
        self.backend_name = backend
        self._backend: AIOpsBackend | None = None

    def _engine(self) -> AIOpsBackend:
        if not self.enabled:
            raise RuntimeError("AI OPS extension is disabled")
        if self.config.report_only:
            raise ValueError(
                "report_only requires legacy SDK patches and is not supported "
                "by AIOpsExtension; use explicit domain Skill plugins"
            )
        from veadk.runtime.codex.config import CodexRuntimeConfig

        if "provider_factory" not in CodexRuntimeConfig.model_fields:
            raise RuntimeError(
                "AI OPS extension requires the public Codex provider API"
            )
        if self._backend is None:
            self._backend = resolve_backend(self.backend_name)
        return self._backend

    def apply(self, agent: Any) -> Any:
        """Compose a fresh Agent, or return it untouched when disabled."""
        if not self.enabled:
            return agent
        return self._engine().create_agent(self.config, self.plugins, agent=agent)

    def create_agent(self) -> Any:
        """Create an Agent using the enabled optional backend."""
        return self._engine().create_agent(self.config, self.plugins)

    def create_app(self, *, agent: Any = None) -> Any:
        """Create a native ADK App including domain-provided ADK plugins."""
        return self._engine().create_app(self.config, self.plugins, agent=agent)


__all__ = ["AIOpsExtension"]
