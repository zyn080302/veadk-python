# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

"""Selected resources cannot leak credentials or survive cancelled preparation."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from veadk.aiops.harness.configuration import HarnessConfigurationError
from veadk.aiops.harness.resources import prepare_resources


def resolved():
    return SimpleNamespace(
        builtin_capabilities=(),
        resource_capabilities={
            "skills": [
                {
                    "skill_id": "selected",
                    "space_id": "space",
                    "version": "3",
                    "environment": {"VOLCENGINE_ACCESS_KEY": "fixture-private"},
                },
            ]
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["valid", "invalid", "escape", "failure", "cancel"])
async def test_resource_worker_isolation_and_cleanup(monkeypatch, tmp_path, outcome):
    roots, processes = [], []
    blocked = asyncio.Event()
    monkeypatch.setenv("MODEL_AGENT_API_KEY", "fixture-unrelated")

    class Process:
        returncode = None
        killed = False

        async def communicate(self, data):
            assert (
                json.loads(data)["environment"]["VOLCENGINE_ACCESS_KEY"]
                == "fixture-private"
            )
            if outcome == "cancel":
                blocked.set()
                await asyncio.Event().wait()
            self.returncode = 1 if outcome == "failure" else 0
            if outcome == "invalid":
                return b'{"private-unexpected": true}', None
            directory = roots[-1] / "method"
            if outcome == "escape":
                directory = tmp_path / "outside"
            directory.mkdir()
            (directory / "SKILL.md").write_text("fixture")
            return json.dumps({"directory": str(directory)}).encode(), None

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    async def spawn(*args, **kwargs):
        assert "fixture-private" not in str(args)
        assert "MODEL_AGENT_API_KEY" not in kwargs["env"]
        roots.append(Path(args[-1]))
        process = Process()
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    if outcome == "cancel":
        task = asyncio.create_task(prepare_resources(resolved()))
        await blocked.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].killed
    elif outcome == "valid":
        resources = await prepare_resources(resolved())
        assert len(resources.directories) == 1
        assert roots[0].is_dir()
        resources.close()
    else:
        with pytest.raises(HarnessConfigurationError):
            await prepare_resources(resolved())
    assert not roots[0].exists()
