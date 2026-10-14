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

"""Resolve an explicitly selected, separately installed AI OPS backend."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from types import SimpleNamespace
from typing import Any, Protocol


class AIOpsBackend(Protocol):
    """API 1: domain composition owned by a trusted installed package."""

    api_version: int

    def create_agent(self, config: Any, plugins: Any, *, agent: Any = None) -> Any: ...

    def create_app(self, config: Any, plugins: Any, *, agent: Any = None) -> Any: ...


def resolve_backend(name: str) -> AIOpsBackend:
    """Load only the selected registration; never mask its failures."""
    selected = [
        point
        for point in entry_points(group="veadk.aiops.backends")
        if point.name == name
    ]
    if len(selected) > 1:
        raise RuntimeError("Multiple AI OPS backends have the selected name")
    if selected:
        backend = selected[0].load()
    elif name == "agentkit":
        try:
            legacy = import_module("agentkit_aiops")
        except ModuleNotFoundError as error:
            if error.name == "agentkit_aiops":
                raise RuntimeError(
                    "AI OPS requires the separately installed agentkit-aiops-agent "
                    "runtime; install the platform wheel supplied with your template"
                ) from None
            raise
        backend = SimpleNamespace(
            api_version=1,
            create_agent=getattr(legacy, "create_agent", None),
            create_app=getattr(legacy, "create_app", None),
        )
    else:
        raise RuntimeError("The selected AI OPS backend is not installed")
    version = getattr(backend, "api_version", None)
    if (
        type(version) is not int
        or version != 1
        or not all(
            callable(getattr(backend, method, None))
            for method in ("create_agent", "create_app")
        )
    ):
        raise RuntimeError("AI OPS backend must implement composition API version 1")
    return backend


__all__ = ["AIOpsBackend"]
