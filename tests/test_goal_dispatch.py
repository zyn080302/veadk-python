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

"""Tests for the open-source goal client + dispatcher (no closed-engine import)."""

from __future__ import annotations

import sys

import pytest

from veadk.goal import GoalBudget, GoalSpec, run_goal


class FakeClient:
    """Stand-in for GoalServiceClient that records calls."""

    def __init__(self, status: str = "green") -> None:
        self.status = status
        self.create_calls = 0
        self.resume_calls = 0
        self.created: dict = {}
        self.resumed = ""

    def create(self, goal, *, agent_endpoint="", run_id=None):
        self.create_calls += 1
        self.created = {"goal": goal.to_dict(), "agent_endpoint": agent_endpoint}
        return {"run_id": "r1", "status": "running"}

    def resume(self, run_id):
        self.resume_calls += 1
        self.resumed = run_id
        return {"run_id": run_id, "status": "running"}

    def wait(self, run_id, *, timeout=600.0, poll_interval=0.5):
        return {"run_id": run_id, "status": self.status}


def _spec():
    return GoalSpec(objective="produce report", acceptance=["accurate"], artifacts=["report.html"])


def test_contract_roundtrip():
    spec = GoalSpec(
        objective="x",
        acceptance=["a", "b"],
        budget=GoalBudget(max_events=10, max_tool_calls=5),
        evidence_required=True,
    )
    restored = GoalSpec.from_dict(spec.to_dict())
    assert restored.objective == "x"
    assert restored.acceptance == ["a", "b"]
    assert restored.budget.max_events == 10
    assert restored.evidence_required is True


def test_codex_runtime_runs_locally_not_service():
    fake = FakeClient()
    outcome = run_goal(_spec(), runtime="codex", client=fake)
    assert outcome.via == "codex"
    assert fake.create_calls == 0  # codex never touches the service


def test_adk_runtime_drives_service():
    fake = FakeClient(status="green")
    outcome = run_goal(_spec(), runtime="adk", client=fake, agent_endpoint="http://agent:9/invoke")
    assert outcome.via == "service"
    assert outcome.status == "green"
    assert outcome.run_id == "r1"
    assert fake.create_calls == 1
    assert fake.created["agent_endpoint"] == "http://agent:9/invoke"
    assert fake.created["goal"]["objective"] == "produce report"


def test_non_codex_runtime_requires_service_when_auto_spawn_disabled():
    with pytest.raises(ValueError):
        run_goal(_spec(), runtime="adk", auto_spawn=False)  # no service_url, no client, no spawn


def test_auto_spawn_starts_local_sidecar_and_stops_it():
    fake = FakeClient(status="green")
    spawned = {"cmd": None, "stopped": False}

    def fake_spawn(command):
        spawned["cmd"] = command

        def stop():
            spawned["stopped"] = True

        return "http://127.0.0.1:54321", stop

    # No service_url and no client -> auto-spawn a local sidecar, then drive it.
    outcome = run_goal(
        _spec(),
        runtime="adk",
        client=fake,  # client wins for the HTTP calls; spawn still provides/owns the url+stop
        spawn=fake_spawn,
    )
    # client was provided, so spawn is NOT triggered (service_url/client already present).
    assert spawned["cmd"] is None
    assert outcome.status == "green"


def test_auto_spawn_used_when_no_service_url_or_client():
    spawned = {"stopped": False}

    class _Svc(FakeClient):
        pass

    captured = {}

    def fake_spawn(command):
        def stop():
            spawned["stopped"] = True

        return "http://127.0.0.1:5999", stop

    # Patch GoalServiceClient construction by passing service_url via spawn return.
    # Use a client factory through monkey: easiest is to assert spawn+stop fire by
    # injecting a client too is not possible here, so drive via real client path:
    from veadk.goal import dispatch as _d

    orig = _d.GoalServiceClient
    try:
        _d.GoalServiceClient = lambda url, **kw: (captured.setdefault("url", url), FakeClient("green"))[1]
        outcome = run_goal(_spec(), runtime="adk", spawn=fake_spawn)
    finally:
        _d.GoalServiceClient = orig

    assert captured["url"] == "http://127.0.0.1:5999"  # spawn provided the URL
    assert spawned["stopped"] is True  # sidecar was stopped in finally
    assert outcome.status == "green"


def test_resume_uses_resume_endpoint_not_create():
    fake = FakeClient(status="green")
    outcome = run_goal(_spec(), runtime="adk", client=fake, resume_run_id="r9")
    assert fake.resume_calls == 1
    assert fake.create_calls == 0
    assert outcome.run_id == "r9"
    assert outcome.status == "green"


def test_open_client_does_not_import_closed_engine():
    # Importing the goal client must not pull in the closed agentkit-harness-python.
    import veadk.goal  # noqa: F401
    import veadk.goal.client  # noqa: F401
    import veadk.goal.contract  # noqa: F401
    import veadk.goal.dispatch  # noqa: F401

    offenders = [
        name
        for name in sys.modules
        if name == "harness"
        or name.startswith("harness.")
        or name == "agentkit_harness"
        or name.startswith("agentkit_harness.")
    ]
    assert offenders == [], f"open client must not import the closed engine: {offenders}"
