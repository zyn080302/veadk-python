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

"""Independent consumer types for Studio's prepared agentkit/v1 contract."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        populate_by_name=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class EnvironmentReference(Contract):
    env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")


def public_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and "?" not in value
            and "#" not in value
            and not any(ord(c) <= 32 or ord(c) == 127 for c in value)
            and parsed.port != 0
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Endpoint must not contain credentials, query or fragment")
    return value


class CloudScope(Contract):
    provider: Literal["volcengine", "byteplus"]
    project: str = Field(min_length=1)
    region: str = Field(min_length=1)


class McpConnection(Contract):
    id: str = Field(min_length=1, max_length=128)
    url: str
    api_key: EnvironmentReference | None = Field(default=None, alias="apiKey")

    _endpoint = field_validator("url")(public_endpoint)


class AgentSelection(Contract):
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    instruction: str
    model: str = Field(min_length=1)
    model_source: Literal["ark", "custom"] = Field(default="ark", alias="modelSource")
    model_provider: Literal["openai", "anthropic", "gemini"] = Field(
        default="openai", alias="modelProvider"
    )
    model_base_url: str = Field(default="", alias="modelBaseUrl")
    model_api_key: EnvironmentReference | None = Field(
        default=None, alias="modelApiKey"
    )
    model_api_key_id: str = Field(default="", alias="modelApiKeyId")
    mcp_servers: list[McpConnection] = Field(
        default_factory=list, alias="mcpServers", max_length=12
    )
    a2a_space_ids: list[str] = Field(
        default_factory=list, alias="a2aSpaceIds", max_length=12
    )
    a2a_spaces_scope: CloudScope | None = Field(default=None, alias="a2aSpacesScope")
    mcp_toolset_ids: list[str] = Field(
        default_factory=list, alias="mcpToolsetIds", max_length=12
    )
    mcp_toolsets_scope: CloudScope | None = Field(
        default=None, alias="mcpToolsetsScope"
    )
    tools: list[Literal["search", "code", "image_generate", "video_generate"]] = Field(
        default_factory=list, max_length=4
    )
    code_sandbox_id: str = Field(default="", alias="codeSandboxId")
    code_sandbox_scope: CloudScope | None = Field(
        default=None, alias="codeSandboxScope"
    )
    knowledgebase_id: str = Field(default="", alias="knowledgebaseId")
    knowledgebase_scope: CloudScope | None = Field(
        default=None, alias="knowledgebaseScope"
    )
    skill_ids: list[str] = Field(default_factory=list, alias="skillIds", max_length=32)
    skills_scope: CloudScope | None = Field(default=None, alias="skillsScope")

    @field_validator("model_base_url")
    @classmethod
    def validate_optional_endpoint(cls, value: str) -> str:
        return public_endpoint(value) if value else value


SECRET_RESOURCE_FIELDS = frozenset(
    {
        "VOLCENGINE_ACCESS_KEY",
        "VOLCENGINE_SECRET_KEY",
        "VOLCENGINE_SESSION_TOKEN",
        "BYTEPLUS_WEB_SEARCH_API_KEY",
        "MODEL_IMAGE_API_KEY",
        "MODEL_VIDEO_API_KEY",
    }
)
PUBLIC_RESOURCE_FIELDS = frozenset(
    {
        "CLOUD_PROVIDER",
        "AGENTKIT_TOOL_REGION",
        "AGENTKIT_TOOL_ID_SCRIPT",
        "AGENTKIT_TOOL_TYPE",
        "AGENTKIT_TOOL_REFERENCE",
        "AGENTKIT_PROJECT_NAME",
        "AGENTKIT_SKILL_HOST",
        "MODEL_IMAGE_NAME",
        "MODEL_IMAGE_API_BASE",
        "MODEL_VIDEO_NAME",
        "MODEL_VIDEO_API_BASE",
    }
)


class ResourceBinding(Contract):
    environment: dict[str, str | EnvironmentReference] = Field(default_factory=dict)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, values):
        for name, value in values.items():
            if name in SECRET_RESOURCE_FIELDS and isinstance(
                value, EnvironmentReference
            ):
                continue
            if name in PUBLIC_RESOURCE_FIELDS and isinstance(value, str):
                if name.endswith("_API_BASE") or name == "AGENTKIT_SKILL_HOST":
                    public_endpoint(value)
                continue
            raise ValueError(
                "Resource environment requires a supported field and credential reference"
            )
        return values


class SkillBinding(ResourceBinding):
    space_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class KnowledgeBinding(ResourceBinding):
    name: str
    resource_id: str = Field(min_length=1)
    project: str


class BuiltinBinding(ResourceBinding):
    name: Literal["web_search", "run_code", "image_generate", "video_generate"]
    error: str = ""


class ResourceCapabilities(Contract):
    knowledgebase: KnowledgeBinding | None = None
    skills: list[SkillBinding] = Field(default_factory=list, max_length=32)


class ModelConnection(Contract):
    api_base: str
    api_key: EnvironmentReference
    provider: Literal["openai", "anthropic", "gemini"] = "openai"
    ark: bool = True

    _endpoint = field_validator("api_base")(public_endpoint)


class RuntimeBindings(Contract):
    model_connection: ModelConnection
    resource_capabilities: ResourceCapabilities = Field(
        default_factory=ResourceCapabilities
    )
    builtin_capabilities: list[BuiltinBinding] = Field(
        default_factory=list, max_length=4
    )


class HarnessDocument(Contract):
    api_version: Literal["agentkit/v1"] = Field(alias="apiVersion")
    kind: Literal["Agent"]
    cloud: CloudScope
    agent: AgentSelection
    runtime: RuntimeBindings
