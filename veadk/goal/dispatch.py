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

"""``--goal`` dispatch: pick the executor by ``runtime``.

``--goal`` is a CLI switch, **not** a new runtime.  It is orthogonal to
``Agent.runtime``:

* ``runtime == "codex"`` -> use codex's own native run/goal locally (no service,
  no closed-engine import).
* any other runtime (``adk`` and future) -> POST the open ``GoalSpec`` to the
  harness service, whose closed ``GoalLoopEngine`` drives the loop and gates
  completion on evidence.

The open client never imports ``agentkit-harness-python``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.request
from typing import Callable, Optional, Tuple

from veadk.goal.client import GoalServiceClient
from veadk.goal.contract import GoalRunOutcome, GoalSpec

_DEFAULT_SIDECAR_CMD = ["agentkit-harness-service", "serve-sidecar", "--port", "0"]


def _run_codex_local(goal: GoalSpec) -> GoalRunOutcome:
    """Seam for the local codex native run/goal path.

    codex ships its own goal loop (ThreadGoal / continue_if_idle / update_goal).
    The full local wiring runs through veADK's codex runtime with a configured
    agent; here we return a dispatched outcome describing the hand-off so the
    open client carries no closed-engine dependency.
    """

    return GoalRunOutcome(
        run_id="codex-local",
        status="dispatched",
        via="codex",
        detail={
            "objective": goal.objective,
            "note": "delegated to codex native run/goal (runtime=codex)",
        },
    )


def run_goal(
    goal: GoalSpec,
    *,
    runtime: str = "adk",
    service_url: str = "",
    agent_endpoint: str = "",
    client: Optional[GoalServiceClient] = None,
    codex_runner: "Optional[Callable[[GoalSpec], GoalRunOutcome]]" = None,
    resume_run_id: str = "",
    wait: bool = True,
    wait_timeout: float = 600.0,
    auto_spawn: bool = True,
    sidecar_command: "Optional[list]" = None,
    spawn: "Optional[Callable[[Optional[list]], Tuple[str, Callable[[], None]]]]" = None,
) -> GoalRunOutcome:
    """Dispatch a goal run by runtime capability.

    ``runtime == "codex"`` runs codex's native goal loop locally. For any other
    runtime, the goal is POSTed to a harness service. When no ``service_url``/
    ``client`` is given and ``auto_spawn`` is True, a Runtime-LOCAL sidecar is
    spawned, used over loopback, and shut down afterwards -- the open client
    still only speaks HTTP and never imports the closed engine.
    """

    if runtime == "codex":
        runner = codex_runner or _run_codex_local
        return runner(goal)

    stop: "Optional[Callable[[], None]]" = None
    try:
        if not (service_url or client):
            if not auto_spawn:
                raise ValueError(
                    f"runtime={runtime!r} has no local goal loop; pass --service-url "
                    "pointing at an agentkit-harness-service (or use --runtime codex)."
                )
            service_url, stop = (spawn or _spawn_local_sidecar)(sidecar_command)

        service = client or GoalServiceClient(service_url)
        if resume_run_id:
            created = service.resume(resume_run_id)
            run_id = created.get("run_id", resume_run_id)
        else:
            created = service.create(goal, agent_endpoint=agent_endpoint)
            run_id = created.get("run_id", "")
        if not run_id:
            return GoalRunOutcome(run_id="", status="failed", via="service", detail=created)
        if not wait:
            return GoalRunOutcome(
                run_id=run_id, status=str(created.get("status", "running")), via="service", detail=created
            )
        final = service.wait(run_id, timeout=wait_timeout)
        return GoalRunOutcome(
            run_id=run_id, status=str(final.get("status", "")), via="service", detail=final
        )
    finally:
        if stop is not None:
            try:
                stop()
            except Exception:
                pass


def _sidecar_command(command: "Optional[list]") -> list:
    if command:
        return list(command)
    env_cmd = os.getenv("VEADK_SIDECAR_CMD", "")
    return shlex.split(env_cmd) if env_cmd else list(_DEFAULT_SIDECAR_CMD)


def _wait_healthy(base_url: str, *, timeout: float = 30.0, interval: float = 0.2) -> None:
    deadline = time.time() + timeout
    last_err: "Optional[Exception]" = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/healthz", timeout=3) as resp:  # noqa: S310
                if resp.status == 200:
                    return
        except Exception as exc:  # not ready yet
            last_err = exc
        time.sleep(interval)
    raise RuntimeError(f"sidecar did not become healthy at {base_url}: {last_err}")


def _spawn_local_sidecar(command: "Optional[list]") -> "Tuple[str, Callable[[], None]]":
    """Spawn a Runtime-local sidecar, return (base_url, stop). The sidecar prints
    a one-line JSON discovery record ({url, pid, ...}) on stdout once bound."""

    cmd = _sidecar_command(command)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    line = proc.stdout.readline() if proc.stdout is not None else ""
    if not line:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"sidecar failed to start (no discovery line) via {cmd}")
    info = json.loads(line)
    url = str(info["url"])
    _wait_healthy(url)

    def stop() -> None:
        try:
            urllib.request.urlopen(  # noqa: S310 - local loopback sidecar
                urllib.request.Request(url.rstrip("/") + "/shutdown", data=b"{}", method="POST"),
                timeout=5,
            )
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    return url, stop


__all__ = ["run_goal"]
