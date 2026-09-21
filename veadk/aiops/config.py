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

"""Credential-free, validated per-agent configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentConfig(BaseModel):
    """Resources and identity; domain knowledge belongs to plugins."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(default="aiops_agent", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    description: str = "自主取证、分析并交付运维诊断报告"
    model_name: str | None = None
    customer_instruction: str = Field(default="", max_length=65536)
    exploration_seconds: float = Field(default=900, gt=0, allow_inf_nan=False)
    invocation_seconds: float = Field(default=2400, gt=0, allow_inf_nan=False)
    max_parallel_tools: int = Field(default=4, ge=1, le=4)
    thinking_mode: Literal["enabled", "disabled"] = "enabled"
    report_only: bool = False
    studio_enabled: bool = False
    sidecar_enabled: bool = False

    @model_validator(mode="after")
    def reserve_report_time(self) -> AgentConfig:
        if self.exploration_seconds >= self.invocation_seconds:
            raise ValueError("invocation_seconds must reserve time after exploration")
        return self


__all__ = ["AgentConfig"]
