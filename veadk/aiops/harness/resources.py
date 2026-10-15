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

"""Prepare exact Skill versions with isolated SDK credentials and cache."""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from veadk.aiops.harness.configuration import HarnessConfigurationError


@dataclass
class PreparedResources:
    directories: tuple[Path, ...] = ()
    temporary: TemporaryDirectory | None = field(default=None, repr=False)

    def close(self):
        if self.temporary is not None:
            self.temporary.cleanup()


async def prepare_resources(resolved):
    if resolved.builtin_capabilities or resolved.resource_capabilities.get(
        "knowledgebase"
    ):
        raise HarnessConfigurationError(
            "This AI OPS template supports MCP services and Skills; other resources require a domain plugin"
        )
    skills = resolved.resource_capabilities.get("skills", ())
    if not skills:
        return PreparedResources()
    temporary = TemporaryDirectory(prefix="aiops-harness-skills-")
    root = Path(temporary.name).resolve()
    try:
        directories = []
        for item in skills:
            environment = {
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT", "PYTHONPATH")
                if key in os.environ
            }
            environment.update(
                HOME=str(root),
                PYTHON_DOTENV_DISABLED="1",
                OTEL_SDK_DISABLED="true",
                LITELLM_LOCAL_MODEL_COST_MAP="True",
            )
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "veadk.aiops.harness.skill_worker",
                str(root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
            )
            try:
                async with asyncio.timeout(180):
                    output, _ = await process.communicate(json.dumps(item).encode())
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if process.returncode or len(output) > 8192:
                raise HarnessConfigurationError("Selected Skill could not be prepared")
            try:
                result = json.loads(output)
                directory = result["directory"]
                if not isinstance(directory, str) or not directory:
                    raise ValueError
                path = Path(directory).resolve()
            except (ValueError, TypeError, KeyError, OSError):
                raise HarnessConfigurationError(
                    "Selected Skill worker returned an invalid directory"
                ) from None
            if root not in path.parents or not (path / "SKILL.md").is_file():
                raise HarnessConfigurationError("Selected Skill directory is invalid")
            directories.append(path)
        return PreparedResources(tuple(directories), temporary)
    except BaseException:
        temporary.cleanup()
        raise
