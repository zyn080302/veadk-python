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

"""Validate public YAML before resolving any credentials or loading the engine."""

from collections.abc import Mapping
from dataclasses import dataclass, field

import yaml
from pydantic import ValidationError

from veadk.aiops.harness.types import (
    AgentSelection,
    CloudScope,
    EnvironmentReference,
    HarnessDocument,
    ResourceBinding,
    RuntimeBindings,
)


class HarnessConfigurationError(ValueError):
    """Safe configuration diagnostics, without input values or parser excerpts."""


class _Loader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise HarnessConfigurationError(
                    "Agent YAML contains invalid or duplicate keys"
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


@dataclass(frozen=True)
class ResolvedMcp:
    id: str
    url: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class ResolvedConfiguration:
    model_api_base: str
    model_api_key: str = field(repr=False)
    model_provider: str
    mcp_servers: tuple[ResolvedMcp, ...]
    resource_capabilities: dict = field(repr=False)
    builtin_capabilities: tuple[dict, ...] = field(repr=False)


def _credential(
    reference: EnvironmentReference | None, environment: Mapping[str, str]
) -> str:
    if reference is None:
        return ""
    value = environment.get(reference.env)
    if not isinstance(value, str) or not value.strip():
        raise HarnessConfigurationError(
            "A required credential environment variable is missing"
        )
    if len(value) > 65536 or any(c in value for c in "\r\n\0"):
        raise HarnessConfigurationError("A credential environment variable is invalid")
    return value


def _resource(binding: ResourceBinding, environment: Mapping[str, str]) -> dict:
    value = binding.model_dump(mode="json", exclude={"environment"})
    value["environment"] = {
        name: _credential(item, environment)
        if isinstance(item, EnvironmentReference)
        else item
        for name, item in binding.environment.items()
    }
    return value


def _scope(
    binding: ResourceBinding, scope: CloudScope | None, *, resolved_region=False
):
    env = binding.environment
    if scope is None or (
        env.get("CLOUD_PROVIDER") != scope.provider
        or not env.get("AGENTKIT_TOOL_REGION")
        or (not resolved_region and env.get("AGENTKIT_TOOL_REGION") != scope.region)
        or (
            "AGENTKIT_PROJECT_NAME" in env
            and env["AGENTKIT_PROJECT_NAME"] != scope.project
        )
    ):
        raise HarnessConfigurationError(
            "Prepared resource does not match the selected cloud scope"
        )


def _validate_bindings(document: HarnessDocument):
    agent, runtime = document.agent, document.runtime
    names = [item.id for item in agent.mcp_servers]
    if len(names) != len(set(names)):
        raise HarnessConfigurationError("MCP identifiers must be unique")
    if agent.a2a_space_ids or agent.mcp_toolset_ids:
        raise HarnessConfigurationError(
            "Unresolved cloud mounts require the Studio managed channel"
        )
    skills = runtime.resource_capabilities.skills
    prepared = [f"{item.space_id}:{item.skill_id}" for item in skills]
    if len(agent.skill_ids) != len(set(agent.skill_ids)) or sorted(prepared) != sorted(
        agent.skill_ids
    ):
        raise HarnessConfigurationError("Prepared Skills do not match the selection")
    for item in skills:
        _scope(item, agent.skills_scope)
    knowledge = runtime.resource_capabilities.knowledgebase
    if bool(agent.knowledgebase_id) != (knowledge is not None):
        raise HarnessConfigurationError(
            "Prepared knowledge base does not match the selection"
        )
    if knowledge is not None:
        _scope(knowledge, agent.knowledgebase_scope, resolved_region=True)
        if (
            agent.knowledgebase_scope is None
            or knowledge.project != agent.knowledgebase_scope.project
        ):
            raise HarnessConfigurationError(
                "Prepared knowledge base project does not match"
            )
    mapping = {
        "search": "web_search",
        "code": "run_code",
        "image_generate": "image_generate",
        "video_generate": "video_generate",
    }
    if len(agent.tools) != len(set(agent.tools)) or sorted(
        item.name for item in runtime.builtin_capabilities
    ) != sorted(mapping[name] for name in agent.tools):
        raise HarnessConfigurationError("Prepared tools do not match the selection")
    for item in runtime.builtin_capabilities:
        if item.error:
            if item.environment:
                raise HarnessConfigurationError(
                    "Failed resource binding must not contain an environment"
                )
            continue
        _scope(
            item,
            agent.code_sandbox_scope if item.name == "run_code" else document.cloud,
        )
        if item.name == "run_code" and (
            not agent.code_sandbox_id
            or (
                item.environment.get("AGENTKIT_TOOL_REFERENCE")
                or item.environment.get("AGENTKIT_TOOL_ID_SCRIPT")
            )
            != agent.code_sandbox_id
        ):
            raise HarnessConfigurationError(
                "Prepared sandbox does not match the selection"
            )


@dataclass(frozen=True)
class HarnessConfiguration:
    public_yaml: str = field(repr=False)
    _document: HarnessDocument = field(repr=False)

    @property
    def agent(self) -> AgentSelection:
        return self._document.agent.model_copy(deep=True)

    @property
    def runtime(self) -> RuntimeBindings:
        return self._document.runtime.model_copy(deep=True)

    def resolve(self, environment: Mapping[str, str]) -> ResolvedConfiguration:
        runtime = self._document.runtime
        resources = runtime.resource_capabilities
        return ResolvedConfiguration(
            model_api_base=runtime.model_connection.api_base,
            model_api_key=_credential(runtime.model_connection.api_key, environment),
            model_provider=runtime.model_connection.provider,
            mcp_servers=tuple(
                ResolvedMcp(item.id, item.url, _credential(item.api_key, environment))
                for item in self._document.agent.mcp_servers
            ),
            resource_capabilities={
                "knowledgebase": _resource(resources.knowledgebase, environment)
                if resources.knowledgebase
                else None,
                "skills": [_resource(item, environment) for item in resources.skills],
            },
            builtin_capabilities=tuple(
                _resource(item, environment) for item in runtime.builtin_capabilities
            ),
        )


def load_configuration(source: str) -> HarnessConfiguration:
    """Read one bounded YAML document; do not interpolate or import user input."""
    try:
        if (
            not isinstance(source, str)
            or not source
            or len(source.encode("utf-8")) > 65536
        ):
            raise HarnessConfigurationError("Agent YAML must contain at most 64 KiB")
        depth = 0
        for count, event in enumerate(yaml.parse(source, Loader=_Loader), 1):
            if count > 20000 or isinstance(event, yaml.AliasEvent):
                raise HarnessConfigurationError(
                    "Agent YAML aliases or excessive nodes are not supported"
                )
            if (
                isinstance(event, (yaml.ScalarEvent, yaml.CollectionStartEvent))
                and event.tag is not None
            ):
                if event.tag not in {
                    f"tag:yaml.org,2002:{name}"
                    for name in ("str", "int", "float", "bool", "null", "map", "seq")
                }:
                    raise HarnessConfigurationError(
                        "Agent YAML contains an unsupported tag"
                    )
            if isinstance(event, yaml.CollectionStartEvent):
                depth += 1
                if depth > 32:
                    raise HarnessConfigurationError("Agent YAML is nested too deeply")
            elif isinstance(event, yaml.CollectionEndEvent):
                depth -= 1
        document = HarnessDocument.model_validate(yaml.load(source, Loader=_Loader))
        _validate_bindings(document)
        return HarnessConfiguration(source, document)
    except HarnessConfigurationError:
        raise
    except (yaml.YAMLError, ValidationError, ValueError, TypeError, RecursionError):
        raise HarnessConfigurationError("Invalid Agent YAML configuration") from None
