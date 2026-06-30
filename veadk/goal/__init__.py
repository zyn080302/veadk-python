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

"""veADK open-source goal client (``--goal`` switch).

Thin client only: an open ``GoalSpec`` contract, an HTTP client for the harness
service, and a runtime-aware dispatcher.  No dependency on the closed
``agentkit-harness-python`` engine.
"""

from __future__ import annotations

from veadk.goal.client import GoalServiceClient
from veadk.goal.contract import GoalBudget, GoalRunOutcome, GoalSpec
from veadk.goal.dispatch import run_goal

__all__ = [
    "GoalBudget",
    "GoalRunOutcome",
    "GoalServiceClient",
    "GoalSpec",
    "run_goal",
]
