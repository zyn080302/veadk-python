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

"""Load a trusted application manifest; never accept model-authored imports."""

from importlib import import_module
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from veadk.aiops.config import AgentConfig
from veadk.aiops.plugin import AgentPlugin


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    plugins: tuple[str, ...] = ()
    skill_directories: tuple[Path, ...] = ()

    @classmethod
    def load(cls, path: str | Path) -> "AgentManifest":
        path = Path(path).resolve(strict=True)
        try:
            manifest = cls.model_validate(
                tomllib.loads(path.read_text(encoding="utf-8"))
            )
        except (ValueError, ValidationError):
            raise ValueError("Invalid AIOps application manifest") from None
        return manifest.model_copy(
            update={
                "skill_directories": tuple(
                    (path.parent / directory).resolve(strict=True)
                    for directory in manifest.skill_directories
                )
            }
        )

    def load_plugins(self) -> tuple[AgentPlugin, ...]:
        result = []
        for reference in self.plugins:
            module, separator, symbol = reference.partition(":")
            if not separator or not module or not symbol.isidentifier():
                raise ValueError("Plugin reference must be module:factory")
            factory = getattr(import_module(module), symbol)
            plugin = factory()
            if not isinstance(plugin, AgentPlugin):
                raise TypeError("Plugin factory must return AgentPlugin")
            result.append(plugin)
        if self.skill_directories:
            result.append(
                AgentPlugin(
                    name="manifest_skills", skill_directories=self.skill_directories
                )
            )
        return tuple(result)


__all__ = ["AgentManifest"]
