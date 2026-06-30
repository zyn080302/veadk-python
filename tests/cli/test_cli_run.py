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

"""CLI tests for ``veadk run --goal``."""

from __future__ import annotations

import json

from click.testing import CliRunner

from veadk.cli.cli_run import run


def test_run_goal_codex_is_local_and_exits_zero():
    result = CliRunner().invoke(run, ["--goal", "summarise the doc", "--runtime", "codex"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["via"] == "codex"
    assert payload["detail"]["objective"] == "summarise the doc"


def test_run_goal_non_codex_without_service_fails():
    result = CliRunner().invoke(run, ["--goal", "x", "--runtime", "adk"])
    assert result.exit_code != 0  # ValueError -> non-zero exit
