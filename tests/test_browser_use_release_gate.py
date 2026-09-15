"""Contract tests for the dynamic Browser Use release gate."""

from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "browser-use-release-gate.yaml"
)


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_browser_use_gate_runs_every_required_quality_layer() -> None:
    workflow = yaml.safe_load(_workflow_text())
    jobs = workflow["jobs"]

    assert {"python", "frontend", "gate"} <= jobs.keys()
    python_commands = "\n".join(
        str(step.get("run", "")) for step in jobs["python"]["steps"]
    )
    frontend_commands = "\n".join(
        str(step.get("run", "")) for step in jobs["frontend"]["steps"]
    )

    for test_path in (
        "tests/frontend/server/studio_tools/test_browser_plan.py",
        "tests/frontend/server/studio_tools/test_browser_observability.py",
        "tests/frontend/server/studio_tools/test_janus_a2a_client.py",
        "tests/frontend/server/studio_tools/test_janus_sandbox.py",
        "tests/frontend/server/studio_tools/test_extensions.py",
        "tests/frontend/server/studio_tools/test_connector.py",
        "tests/cli/test_frontend_runtime_proxy.py",
        "tests/integrations/agentkit/test_studio_channel.py",
    ):
        assert test_path in python_commands
    assert "ruff check" in python_commands
    assert "pyright" in python_commands
    assert "git diff --check" in python_commands
    assert "':(exclude)veadk/webui/**'" in python_commands

    assert "npm test" in frontend_commands
    assert "npx tsc --noEmit" in frontend_commands
    assert "npm run build" in frontend_commands
    assert "npm run test:webui-assets" in frontend_commands


def test_browser_use_gate_is_fail_closed_and_tracks_product_paths() -> None:
    workflow_text = _workflow_text()
    workflow = yaml.safe_load(workflow_text)
    trigger = workflow[True]
    tracked_paths = set(trigger["pull_request"]["paths"])

    assert "frontend/**" in tracked_paths
    assert "veadk/integrations/agentkit/**" in tracked_paths
    assert "veadk/cli/cli_frontend.py" in tracked_paths
    assert "tests/test_browser_use_release_gate.py" in tracked_paths

    gate = workflow["jobs"]["gate"]
    assert set(gate["needs"]) == {"python", "frontend"}
    assert gate["if"] == "always()"
    gate_commands = "\n".join(str(step.get("run", "")) for step in gate["steps"])
    assert 'test "$PYTHON_RESULT" = success' in gate_commands
    assert 'test "$FRONTEND_RESULT" = success' in gate_commands


def test_browser_use_pyright_gate_checks_owned_modules_without_importing_cli_debt() -> (
    None
):
    """Keep the Browser gate green without hiding its independently typed code.

    ``cli_frontend.py`` is a large shared composition root with unrelated existing
    SDK/CICD typing debt.  Its Browser wiring is exercised by the proxy integration
    tests and Ruff above; Pyright must stay scoped to the independently owned
    Browser/Studio modules so unrelated debt cannot permanently disable this gate.
    """

    workflow = yaml.safe_load(_workflow_text())
    python_steps = workflow["jobs"]["python"]["steps"]
    pyright_commands = "\n".join(
        str(step.get("run", ""))
        for step in python_steps
        if "pyright" in str(step.get("run", ""))
    )

    for module_path in (
        "frontend/server/studio_tools/browser_observability.py",
        "frontend/server/studio_tools/browser_plan.py",
        "frontend/server/studio_tools/extensions/browser_use.py",
        "frontend/server/studio_tools/janus_a2a_client.py",
        "frontend/server/studio_tools/janus_sandbox.py",
        "veadk/integrations/agentkit/app.py",
        "veadk/integrations/agentkit/studio_channel/history.py",
    ):
        assert module_path in pyright_commands
    assert "veadk/cli/cli_frontend.py" not in pyright_commands
