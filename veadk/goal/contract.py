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

"""Open-source goal contract for the veADK thin client.

This is pure data: a JSON-serialisable description of a goal.  It carries **no**
dependency on the closed-source ``agentkit-harness-python`` engine -- the open
client only needs to *describe* a goal and hand it to the harness service over
HTTP.  The closed engine reconstructs its own richer ``GoalSpec`` from this.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class GoalBudget:
    """Run limits (maps onto the service/engine budget knobs)."""

    max_events: Optional[int] = None
    max_wall_time_seconds: Optional[float] = None
    max_tool_calls: Optional[int] = None
    max_tool_failures: Optional[int] = None

    def to_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "GoalBudget":
        data = data or {}
        return cls(
            max_events=data.get("max_events"),
            max_wall_time_seconds=data.get("max_wall_time_seconds"),
            max_tool_calls=data.get("max_tool_calls"),
            max_tool_failures=data.get("max_tool_failures"),
        )


@dataclass
class GoalSpec:
    """A goal as the open client describes it (acceptance as plain strings)."""

    objective: str
    acceptance: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    verification_plan: list = field(default_factory=list)
    budget: GoalBudget = field(default_factory=GoalBudget)
    evidence_required: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "acceptance": list(self.acceptance),
            "artifacts": list(self.artifacts),
            "constraints": list(self.constraints),
            "verification_plan": list(self.verification_plan),
            "budget": self.budget.to_dict(),
            "evidence_required": self.evidence_required,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoalSpec":
        data = data or {}
        return cls(
            objective=str(data.get("objective", "")),
            acceptance=list(data.get("acceptance") or []),
            artifacts=list(data.get("artifacts") or []),
            constraints=list(data.get("constraints") or []),
            verification_plan=list(data.get("verification_plan") or []),
            budget=GoalBudget.from_dict(data.get("budget")),
            evidence_required=bool(data.get("evidence_required", False)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class GoalRunOutcome:
    """The terminal outcome of dispatching a goal run."""

    run_id: str = ""
    status: str = ""
    via: str = ""  # "codex" (local) | "service"
    detail: dict = field(default_factory=dict)

    @property
    def is_green(self) -> bool:
        return self.status == "green"

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = ["GoalBudget", "GoalRunOutcome", "GoalSpec"]
