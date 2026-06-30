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

"""HTTP client for the harness service goal-run API.

Thin and dependency-light: it speaks the service's ``/v1/goal/runs`` HTTP/SSE
surface and nothing else.  It does **not** import the closed engine.  A
``session`` (anything exposing ``post(url, json=...)`` / ``get(url)`` returning
an object with ``.status_code`` and ``.json()``) can be injected for tests;
otherwise an ``httpx.Client`` is created lazily.
"""

from __future__ import annotations

import time
from typing import Optional

from veadk.goal.contract import GoalSpec

_TERMINAL = {"green", "budget_exhausted", "stalled", "cancelled", "failed", "unsupported", "done"}


class GoalServiceClient:
    """Client for ``POST /v1/goal/runs`` + status/events/cancel/resume."""

    def __init__(self, base_url: str, *, timeout: float = 300.0, session: object = None) -> None:
        self._base = (base_url or "").rstrip("/")
        self._timeout = timeout
        self._session = session

    def _client(self):
        if self._session is not None:
            return self._session
        import httpx

        self._session = httpx.Client(timeout=self._timeout)
        return self._session

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def create(self, goal: GoalSpec, *, agent_endpoint: str = "", run_id: Optional[str] = None) -> dict:
        body = {"goal": goal.to_dict(), "agent_endpoint": agent_endpoint}
        if run_id:
            body["run_id"] = run_id
        response = self._client().post(self._url("/v1/goal/runs"), json=body)
        return response.json()

    def get(self, run_id: str) -> dict:
        response = self._client().get(self._url(f"/v1/goal/runs/{run_id}"))
        return response.json()

    def cancel(self, run_id: str) -> dict:
        response = self._client().post(self._url(f"/v1/goal/runs/{run_id}/cancel"), json={})
        return response.json()

    def resume(self, run_id: str) -> dict:
        response = self._client().post(self._url(f"/v1/goal/runs/{run_id}/resume"), json={})
        return response.json()

    def wait(self, run_id: str, *, timeout: float = 600.0, poll_interval: float = 0.5) -> dict:
        deadline = time.time() + timeout
        latest: dict = {}
        while time.time() < deadline:
            latest = self.get(run_id)
            if str(latest.get("status")) in _TERMINAL:
                return latest
            time.sleep(poll_interval)
        return latest

    def close(self) -> None:
        session = self._session
        if session is not None and hasattr(session, "close"):
            try:
                session.close()
            except Exception:
                pass


__all__ = ["GoalServiceClient"]
