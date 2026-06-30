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

"""``veadk run --goal`` -- run a goal to evidence-verified completion.

``--goal`` is a switch orthogonal to ``--runtime``: ``--runtime codex`` runs
codex's native goal loop locally; any other runtime is driven by the harness
service (``--service-url``).  This command imports no closed-engine code.
"""

from __future__ import annotations

import json

import click


@click.command("run")
@click.option("--goal", "goal_text", required=True, help="The objective to accomplish.")
@click.option(
    "--runtime",
    default="adk",
    show_default=True,
    help="Execution backend. 'codex' runs locally; others go through the harness service.",
)
@click.option("--service-url", default="", help="harness-service base URL (required for non-codex runtimes).")
@click.option("--agent-endpoint", default="", help="Agent /invoke endpoint the service engine drives.")
@click.option("--acceptance", "acceptance", multiple=True, help="An acceptance criterion (repeatable).")
@click.option("--artifact", "artifacts", multiple=True, help="A required output artifact path (repeatable).")
@click.option("--constraint", "constraints", multiple=True, help="A constraint (repeatable).")
@click.option("--budget-max-events", type=int, default=None, help="Max loop events before graceful exit.")
@click.option("--budget-max-tool-calls", type=int, default=None, help="Max tool calls.")
@click.option("--evidence-required", is_flag=True, default=False, help="Require fresh evidence to complete.")
@click.option("--resume", "resume_run_id", default="", help="Resume an existing run_id.")
@click.option("--no-wait", is_flag=True, default=False, help="Return immediately with the run_id.")
def run(
    goal_text: str,
    runtime: str,
    service_url: str,
    agent_endpoint: str,
    acceptance: tuple,
    artifacts: tuple,
    constraints: tuple,
    budget_max_events,
    budget_max_tool_calls,
    evidence_required: bool,
    resume_run_id: str,
    no_wait: bool,
) -> None:
    """Run a goal until it is verified complete (by evidence, not self-claim)."""

    # Imported lazily to keep CLI startup fast and the import surface clean.
    from veadk.goal import GoalBudget, GoalSpec, run_goal

    spec = GoalSpec(
        objective=goal_text,
        acceptance=list(acceptance),
        artifacts=list(artifacts),
        constraints=list(constraints),
        budget=GoalBudget(max_events=budget_max_events, max_tool_calls=budget_max_tool_calls),
        evidence_required=evidence_required,
    )
    outcome = run_goal(
        spec,
        runtime=runtime,
        service_url=service_url,
        agent_endpoint=agent_endpoint,
        resume_run_id=resume_run_id,
        wait=not no_wait,
    )
    click.echo(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    if outcome.status not in {"green", "dispatched", "running"}:
        raise SystemExit(1)
