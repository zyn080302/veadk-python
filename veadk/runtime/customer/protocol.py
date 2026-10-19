"""Managed customer Shared wire values, independent of Studio manifests."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    field_validator,
    model_validator,
)

PROTOCOL = "studio-tool-channel/1"
CHANNEL_PATH = "/managed/harness/studio-channel/v1"


class CustomerChannelError(RuntimeError):
    """A fixed diagnostic code without configuration, headers or remote bodies."""


class _Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class CustomerTool(_Snapshot):
    """One trusted executor declaration for the customer Host."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=4096, repr=False)
    input_schema: dict[str, JsonValue] = Field(repr=False)
    executor_revision: str = Field(min_length=1, max_length=128)
    timeout_ms: int = Field(default=600000, ge=1, le=1800000, strict=True)
    idempotent: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    long_running: Literal[True] | None = None
    source: Literal["mcp", "studio", "knowledgebase"]

    @field_validator("input_schema")
    @classmethod
    def check_schema(cls, value):
        if value.get("type") != "object":
            raise ValueError("Tool schema must describe an object")
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError:
            raise ValueError("Invalid tool schema") from None

        # External schema references would perform uncontrolled network I/O.
        def check_refs(node):
            if isinstance(node, dict):
                for key in ("$ref", "$dynamicRef"):
                    ref = node.get(key)
                    if ref is not None and (
                        not isinstance(ref, str) or not ref.startswith("#")
                    ):
                        raise ValueError("Only local schema references are supported")
                for item in node.values():
                    check_refs(item)
            elif isinstance(node, list):
                for item in node:
                    check_refs(item)

        check_refs(value)
        return value


class CustomerSkill(_Snapshot):
    """A complete, read-only text snapshot; never execute resource contents."""

    name: str = Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$", max_length=64)
    description: str = Field(min_length=1, max_length=1024, repr=False)
    instructions: str = Field(min_length=1, repr=False)
    references: dict[str, str] = Field(default_factory=dict, repr=False)
    assets: dict[str, str] = Field(default_factory=dict, repr=False)
    scripts: dict[str, str] = Field(default_factory=dict, repr=False)

    @field_validator("scripts")
    @classmethod
    def readonly(cls, value):
        if value:
            raise ValueError("Customer skills must be read-only")
        return value


def catalog_revision(tools: tuple[CustomerTool, ...]) -> str:
    """Hash Shared defaults and sources, excluding unset optional values."""
    payload = json.dumps(
        [
            tool.model_dump(mode="json", exclude_none=True)
            for tool in sorted(tools, key=lambda item: item.name)
        ],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


class CustomerRunRequest(_Snapshot):
    """Server-owned input for one invocation, carrying only its new message.

    Configuration and environment remain SecretStr until the HTTP boundary.
    Run/channel/scope identifiers are generated afresh by default.
    """

    app_name: str = Field(
        pattern=r"^(?:studio_debug|managed_[A-Za-z0-9_-]+)$", max_length=128
    )
    user_id: str = Field(min_length=1, max_length=256, repr=False)
    session_id: str = Field(min_length=1, max_length=128, repr=False)
    new_message: dict[str, JsonValue] = Field(repr=False)
    agent_config: SecretStr = Field(repr=False)
    environment: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    tools: tuple[CustomerTool, ...] = Field(default=(), max_length=64, repr=False)
    skills: tuple[CustomerSkill, ...] = Field(default=(), max_length=16, repr=False)
    thinking: Literal["enabled", "disabled"] | None = None
    channel_id: str = Field(
        default_factory=lambda: uuid4().hex, pattern=r"^[A-Za-z0-9_-]{16,128}$"
    )
    run_id: str = Field(
        default_factory=lambda: uuid4().hex, min_length=1, max_length=128
    )
    scope_id: str = Field(
        default_factory=lambda: uuid4().hex, min_length=1, max_length=256
    )

    @model_validator(mode="after")
    def validate_request(self):
        if not self.agent_config.get_secret_value().strip():
            raise ValueError("Complete agent configuration is required")
        if len({tool.name for tool in self.tools}) != len(self.tools):
            raise ValueError("Duplicate tool names")
        if len({skill.name for skill in self.skills}) != len(self.skills):
            raise ValueError("Duplicate skill names")
        if self.new_message.get("role") != "user":
            raise ValueError("Only a new user message is supported")
        parts = self.new_message.get("parts")
        if (
            not isinstance(parts, list)
            or not parts
            or not all(isinstance(p, dict) for p in parts)
        ):
            raise ValueError("User message must contain parts")
        return self

    @property
    def catalog_revision(self) -> str:
        return catalog_revision(self.tools)

    def to_wire(self) -> dict[str, JsonValue]:
        """Serialize inside trusted local HTTP code; never log the result."""
        payload = {
            "app_name": self.app_name,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "new_message": self.new_message,
            "streaming": True,
        }
        if self.thinking is not None:
            payload["thinking"] = self.thinking
        return {
            "protocol": PROTOCOL,
            "channel_id": self.channel_id,
            "run_id": self.run_id,
            "scope_id": self.scope_id,
            "catalog_revision": self.catalog_revision,
            "tools": [t.model_dump(mode="json", exclude_none=True) for t in self.tools],
            "skills": [s.model_dump(mode="json") for s in self.skills],
            "payload": payload,
            "agent_config": self.agent_config.get_secret_value(),
            "environment": {
                k: v.get_secret_value() for k, v in self.environment.items()
            },
        }
