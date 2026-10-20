"""Server-owned configuration; never deserialize this from an HTTP request."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import httpx
from pydantic import SecretStr

from .dispatch import Executor
from .protocol import CustomerRunRequest, CustomerSkill, CustomerTool
from .session_store import CustomerSessionStore


@dataclass(frozen=True, repr=False)
class CustomerRuntimeConfig:
    """Compose existing customer components using trusted local dependencies.

    Call store.initialize() separately. Headers and executor bodies stay under
    caller ownership. No environment lookup, model construction or HTTP occurs
    in this constructor. A transport is optional local test infrastructure.
    """

    endpoint: str
    engine_id: str
    remote_app: str
    agent_config: SecretStr
    store: CustomerSessionStore
    environment: Mapping[str, SecretStr] = field(default_factory=dict)
    tools: tuple[CustomerTool, ...] = ()
    skills: tuple[CustomerSkill, ...] = ()
    executors: Mapping[str, Executor] = field(default_factory=dict)
    protocol: str = field(default="shared", kw_only=True)
    native_tools: bool = field(default=False, kw_only=True)
    headers: Callable[[], Mapping[str, str]] | None = None
    transport: httpx.AsyncBaseTransport | None = None
    total_timeout: float = 165
    operation_timeout: float = 10
    cleanup_timeout: float = 10
    max_concurrency: int = 8
    event_queue_size: int = 16
    _binding_id: str = field(init=False)

    def __post_init__(self):
        from .client import _validate_endpoint

        _validate_endpoint(self.endpoint)
        if self.protocol not in ("shared", "native"):
            raise ValueError("Invalid customer protocol")
        if not isinstance(self.store, CustomerSessionStore):
            raise ValueError("CustomerSessionStore is required")
        if not isinstance(self.engine_id, str) or not 0 < len(self.engine_id) <= 128:
            raise ValueError("Invalid engine revision")
        if not isinstance(self.agent_config, SecretStr) or any(
            not isinstance(v, SecretStr) for v in self.environment.values()
        ):
            raise ValueError("Customer configuration requires SecretStr values")
        for value in (self.total_timeout, self.operation_timeout, self.cleanup_timeout):
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("Invalid runtime timeout")
        for value, upper in ((self.max_concurrency, 64), (self.event_queue_size, 256)):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("Invalid runtime capacity")
        if self.headers is not None and not callable(self.headers):
            raise ValueError("Headers require a server callback")
        snapshot = CustomerRunRequest(
            app_name=self.remote_app,
            user_id="validation",
            session_id="validation",
            new_message={"role": "user", "parts": [{"text": "validation"}]},
            agent_config=self.agent_config,
            environment=dict(self.environment),
            tools=copy.deepcopy(self.tools),
            skills=copy.deepcopy(self.skills),
        )
        if self.protocol == "native":
            from .native_channel import _native_payload

            _native_payload(snapshot, snapshot.new_message)
        functions = dict(self.executors)
        if type(self.native_tools) is not bool or (self.native_tools and functions):
            raise ValueError("Native tools cannot use explicit executors")
        if (
            not self.native_tools
            and set(functions) != {tool.name for tool in snapshot.tools}
        ) or any(
            not inspect.iscoroutinefunction(fn)
            and not inspect.iscoroutinefunction(getattr(fn, "__call__", None))
            for fn in functions.values()
        ):
            raise ValueError("A matching asynchronous executor catalog is required")
        object.__setattr__(self, "tools", snapshot.tools)
        object.__setattr__(self, "skills", snapshot.skills)
        object.__setattr__(
            self, "environment", MappingProxyType(dict(snapshot.environment))
        )
        object.__setattr__(self, "executors", MappingProxyType(functions))
        # Bind content/configuration changes, but not rotating transport headers.
        payload = snapshot.to_wire()
        for key in ("run_id", "channel_id", "scope_id"):
            payload.pop(key)
        payload.update(endpoint=self.endpoint.rstrip("/"), engine_id=self.engine_id)
        if self.native_tools:
            payload["native_tools"] = True
        if self.protocol != "shared":
            payload["protocol"] = self.protocol
        digest = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest()
        object.__setattr__(self, "_binding_id", "customer-" + digest)

    def __deepcopy__(self, memo):
        # Store/HTTP transports are service-owned, not per-request resources.
        return self


def check_customer_agent(agent, run_config=None):
    """Reject unsupported ADK behavior before any customer or model I/O."""
    from veadk.runtime.compat import explicit_fields

    if not isinstance(
        getattr(agent, "customer_runtime_config", None), CustomerRuntimeConfig
    ):
        raise ValueError(
            "customer_runtime_config requires a server-owned CustomerRuntimeConfig"
        )
    allowed = {
        "id",
        "name",
        "description",
        "runtime",
        "customer_runtime_config",
        "short_term_memory",
        "run_processor",
    }
    fields = explicit_fields(agent) | frozenset(getattr(agent, "model_fields_set", ()))
    if agent.customer_runtime_config.native_tools:
        allowed.update(
            {
                "tools",
                "before_tool_callback",
                "after_tool_callback",
                "on_tool_error_callback",
            }
        )
    for name in sorted(fields - allowed):
        if (
            name in {"rerun_on_resume", "wait_for_output"}
            and type(getattr(agent, name, None)) is bool
        ):
            continue
        if name == "parent_agent" and getattr(agent, name, None) is None:
            continue
        if name == "mode" and getattr(agent, name, None) == "chat":
            continue
        # BaseAgent.clone reassigns all list fields, including empty defaults.
        if name in {
            "tools",
            "skills",
            "sub_agents",
            "tracers",
            "model_fallbacks",
        } and not getattr(agent, name, None):
            continue
        raise ValueError("Unsupported customer Agent field: " + name)
    if getattr(agent, "model", None) or getattr(agent, "model_api_key", None):
        raise ValueError("Customer Runtime cannot use a local model")
    if getattr(agent, "runtime", None) != "customer":
        raise ValueError("A customer Agent cannot switch runtime")
    if run_config is not None:
        supported = {"streaming_mode"}
        if getattr(run_config, "custom_metadata", None) is None:
            supported.add("custom_metadata")
        if set(getattr(run_config, "model_fields_set", ())) - supported:
            raise ValueError("Unsupported customer RunConfig option")
