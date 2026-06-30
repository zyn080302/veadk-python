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

"""Tests for veADK's GoalServiceClient (HTTP wiring, with a fake session)."""

from __future__ import annotations

from veadk.goal import GoalServiceClient, GoalSpec


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, *, get_sequence=None):
        self.posts = []
        self.gets = []
        self._get_sequence = list(get_sequence or [])

    def post(self, url, json=None, **kwargs):
        self.posts.append((url, json))
        return _Resp({"run_id": "gr-1", "status": "running"})

    def get(self, url, **kwargs):
        self.gets.append(url)
        if self._get_sequence:
            return _Resp(self._get_sequence.pop(0))
        return _Resp({"run_id": "gr-1", "status": "green"})


def test_create_posts_goal_and_agent_endpoint():
    session = _FakeSession()
    client = GoalServiceClient("http://svc/", session=session)
    created = client.create(
        GoalSpec(objective="x", artifacts=["r.html"]), agent_endpoint="http://agent/invoke"
    )
    assert created["run_id"] == "gr-1"
    url, body = session.posts[0]
    assert url == "http://svc/v1/goal/runs"
    assert body["agent_endpoint"] == "http://agent/invoke"
    assert body["goal"]["objective"] == "x"
    assert body["goal"]["artifacts"] == ["r.html"]


def test_wait_polls_until_terminal():
    # running -> running -> green
    session = _FakeSession(
        get_sequence=[
            {"status": "running"},
            {"status": "running"},
            {"status": "green", "run_id": "gr-1"},
        ]
    )
    client = GoalServiceClient("http://svc", session=session)
    final = client.wait("gr-1", timeout=5, poll_interval=0.0)
    assert final["status"] == "green"
    assert len(session.gets) == 3  # polled until terminal


def test_cancel_and_resume_hit_correct_paths():
    session = _FakeSession()
    client = GoalServiceClient("http://svc", session=session)
    client.cancel("gr-9")
    client.resume("gr-9")
    paths = [url for url, _ in session.posts]
    assert "http://svc/v1/goal/runs/gr-9/cancel" in paths
    assert "http://svc/v1/goal/runs/gr-9/resume" in paths
