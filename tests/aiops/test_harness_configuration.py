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

"""The independent Studio producer and AI OPS image share a YAML contract."""

from copy import deepcopy

import pytest
import yaml

from veadk.aiops.harness.configuration import (
    HarnessConfigurationError,
    load_configuration,
)


def document():
    return {
        "apiVersion": "agentkit/v1",
        "kind": "Agent",
        "cloud": {
            "provider": "volcengine",
            "project": "default",
            "region": "cn-beijing",
        },
        "agent": {
            "name": "应用排障助手",
            "instruction": "客户附加规则",
            "model": "fixture-model",
            "mcpServers": [
                {
                    "id": "metrics",
                    "url": "https://metrics.invalid/mcp",
                    "apiKey": {"env": "METRICS_KEY"},
                },
                {
                    "id": "logs",
                    "url": "https://logs.invalid/sse",
                    "apiKey": {"env": "LOGS_KEY"},
                },
            ],
        },
        "runtime": {
            "model_connection": {
                "api_base": "https://model.invalid/v1",
                "api_key": {"env": "MODEL_KEY"},
                "provider": "openai",
                "ark": True,
            },
        },
    }


def load(value):
    return load_configuration(yaml.safe_dump(value, allow_unicode=True))


def test_reference_roundtrip_never_resolves_secrets_in_public_yaml():
    source = yaml.safe_dump(document(), allow_unicode=True)
    config = load_configuration(source)
    private = config.resolve(
        {
            "MODEL_KEY": "fixture-model-secret",
            "METRICS_KEY": "fixture-metrics-secret",
            "LOGS_KEY": "fixture-logs-secret",
        }
    )
    assert config.public_yaml == source
    assert private.model_api_key == "fixture-model-secret"
    assert [item.api_key for item in private.mcp_servers] == [
        "fixture-metrics-secret",
        "fixture-logs-secret",
    ]
    assert "fixture-model-secret" not in repr(private)
    assert "fixture-metrics-secret" not in repr(private.mcp_servers)
    assert "fixture-model-secret" not in config.public_yaml
    assert config.agent.instruction == "客户附加规则"


@pytest.mark.parametrize(
    "source",
    [
        "apiVersion: agentkit/v1\napiVersion: secret-must-not-echo",
        "a: &a [*a]",
        "!!python/object/apply:os.system ['secret-must-not-echo']",
        "x: [" + "[" * 40 + "]" * 40 + "]",
        "x: " + "a" * 65536,
        "---\na: b\n---\nx: y",
    ],
)
def test_invalid_yaml_is_bounded_and_has_no_source_in_public_error(source):
    with pytest.raises(HarnessConfigurationError) as caught:
        load_configuration(source)
    assert "secret-must-not-echo" not in str(caught.value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(apiVersion="agentkit/v2"),
        lambda d: d["runtime"]["model_connection"].update(
            api_key="secret-must-not-echo"
        ),
        lambda d: d["agent"]["mcpServers"][0].update(apiKey="secret-must-not-echo"),
        lambda d: d["agent"]["mcpServers"][0].update(
            url="https://metrics.invalid/mcp?token=secret-must-not-echo"
        ),
        lambda d: d["agent"]["mcpServers"].append(
            deepcopy(d["agent"]["mcpServers"][0])
        ),
        lambda d: d["agent"].update(pythonModule="secret-must-not-echo"),
        lambda d: d.pop("runtime"),
        lambda d: d["agent"].update(skillIds=["space:skill"]),
        lambda d: d["agent"].update(tools=["search"]),
    ],
)
def test_invalid_or_unprepared_bindings_fail_before_server_start(mutation):
    value = document()
    mutation(value)
    with pytest.raises(HarnessConfigurationError) as caught:
        load(value)
    assert "secret-must-not-echo" not in str(caught.value)


def test_clearing_mcp_selection_does_not_inherit_previous_environment():
    value = document()
    value["agent"]["mcpServers"] = []
    private = load(value).resolve(
        {"MODEL_KEY": "fixture-key", "MCP_SERVERS_JSON": "old-private-value"}
    )
    assert private.mcp_servers == ()


def test_missing_reference_is_explicit_and_not_replaced_by_generic_api_key():
    with pytest.raises(HarnessConfigurationError):
        load(document()).resolve({"OPENAI_API_KEY": "fixture-unrelated-key"})


def test_skill_selection_requires_exact_version_scope_and_reference_binding():
    value = document()
    value["agent"].update(
        skillIds=["space:report"], skillsScope=deepcopy(value["cloud"])
    )
    binding = {
        "space_id": "space",
        "skill_id": "report",
        "version": "3",
        "environment": {
            "CLOUD_PROVIDER": "volcengine",
            "AGENTKIT_TOOL_REGION": "cn-beijing",
            "AGENTKIT_PROJECT_NAME": "default",
            "VOLCENGINE_ACCESS_KEY": {"env": "RESOURCE_AK"},
            "VOLCENGINE_SECRET_KEY": {"env": "RESOURCE_SK"},
        },
    }
    value["runtime"]["resource_capabilities"] = {"skills": [binding]}
    config = load(value)
    assert config.runtime.resource_capabilities.skills[0].version == "3"
    binding["environment"]["AGENTKIT_TOOL_REGION"] = "wrong-region"
    with pytest.raises(HarnessConfigurationError):
        load(value)


def test_configuration_is_a_snapshot_not_mutable_caller_data():
    value = document()
    config = load(value)
    value["agent"]["mcpServers"].clear()
    assert len(config.agent.mcp_servers) == 2
