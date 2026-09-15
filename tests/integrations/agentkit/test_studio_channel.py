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

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk.agents import Agent as AdkAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner as AdkRunner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from pydantic import PrivateAttr

from veadk.integrations.agentkit.studio_channel import (
    PROTOCOL_VERSION,
    StudioExternalToolset,
    StudioRemoteTool,
    StudioToolManifest,
    bind_studio_tools,
    catalog_revision,
    mount_studio_channel_routes,
)
from veadk.integrations.agentkit.studio_channel.history import (
    StudioToolHistoryPlugin,
)
from veadk.integrations.agentkit.studio_channel.routes import _StudioChannelConnection


def _manifest(name: str = "studio_multiply") -> dict[str, Any]:
    return {
        "name": name,
        "description": "Multiply two integers in the Studio BFF.",
        "input_schema": {
            "type": "object",
            "properties": {
                "left": {"type": "integer"},
                "right": {"type": "integer"},
            },
            "required": ["left", "right"],
            "additionalProperties": False,
        },
        "executor_revision": "demo-v1",
        "timeout_ms": 30000,
        "idempotent": True,
        "risk_level": "low",
    }


class _UnknownToolThenAnswerModel(BaseLlm):
    model: str = "offline-unknown-tool"
    _requests: list[list[types.Content]] = PrivateAttr(default_factory=list)

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncIterator[LlmResponse]:
        del stream
        self._requests.append(
            [content.model_copy(deep=True) for content in llm_request.contents]
        )
        if len(self._requests) == 1:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_function_call(
                            name="browser_use",
                            args={"task": "open example.com"},
                        )
                    ],
                )
            )
            return
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="Continued without the unavailable tool.")],
            )
        )


def test_catalog_revision_is_stable_across_tool_order() -> None:
    first = _manifest("studio_first")
    second = _manifest("studio_second")

    assert catalog_revision([first, second]) == catalog_revision([second, first])


def test_runtime_rejects_an_invalid_json_schema() -> None:
    manifest = _manifest()
    manifest["input_schema"]["properties"]["left"]["type"] = "not-a-json-type"

    with pytest.raises(ValueError, match="input_schema is invalid"):
        StudioToolManifest.model_validate(manifest)


def test_manifest_accepts_a_fifteen_minute_tool_timeout() -> None:
    manifest = _manifest()
    manifest["timeout_ms"] = 15 * 60 * 1000

    validated = StudioToolManifest.model_validate(manifest)

    assert validated.timeout_ms == 15 * 60 * 1000


def test_manifest_rejects_a_tool_timeout_over_thirty_minutes() -> None:
    manifest = _manifest()
    manifest["timeout_ms"] = 30 * 60 * 1000 + 1

    with pytest.raises(ValueError, match="less than or equal to 1800000"):
        StudioToolManifest.model_validate(manifest)


def test_remote_tool_exposes_manifest_schema_and_dispatches() -> None:
    calls: list[dict[str, Any]] = []

    class Dispatcher:
        async def call_tool(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return {"product": 42}

    tool = StudioRemoteTool(
        manifest=StudioToolManifest.model_validate(_manifest()),
        dispatcher=Dispatcher(),
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision="revision-1",
    )

    declaration = tool._get_declaration()
    assert declaration.name == "studio_multiply"
    assert declaration.parameters_json_schema == _manifest()["input_schema"]

    result = asyncio.run(
        tool.run_async(
            args={"left": 6, "right": 7},
            tool_context=cast(
                ToolContext,
                SimpleNamespace(function_call_id="adk-function-call-1"),
            ),
        )
    )
    assert result == {"product": 42}
    assert calls[0]["run_id"] == "run-1"
    assert calls[0]["arguments"] == {"left": 6, "right": 7}
    assert calls[0]["function_call_id"] == "adk-function-call-1"


def test_successful_codex_tool_skips_outer_model_summarization() -> None:
    class Dispatcher:
        async def call_tool(self, **kwargs: Any) -> Any:
            del kwargs
            return {
                "ok": True,
                "message": "Codex final answer",
                "codex_activity": {"events": [{"status": "completed"}]},
            }

    tool = StudioRemoteTool(
        manifest=StudioToolManifest.model_validate(
            _manifest("delegate_to_codex_sandbox")
        ),
        dispatcher=Dispatcher(),
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision="revision-1",
    )
    actions = SimpleNamespace(skip_summarization=None)

    result = asyncio.run(
        tool.run_async(
            args={"task": "review"},
            tool_context=cast(
                ToolContext,
                SimpleNamespace(
                    function_call_id="adk-function-call-1",
                    actions=actions,
                ),
            ),
        )
    )

    assert result["message"] == "Codex final answer"
    assert actions.skip_summarization is True


@pytest.mark.parametrize(
    ("tool_name", "result"),
    [
        ("delegate_to_codex_sandbox", {"ok": False, "error": "busy"}),
        ("studio_multiply", {"ok": True, "message": "42"}),
    ],
)
def test_remote_tool_keeps_outer_summarization_for_nonfinal_results(
    tool_name: str,
    result: dict[str, Any],
) -> None:
    class Dispatcher:
        async def call_tool(self, **kwargs: Any) -> Any:
            del kwargs
            return result

    tool = StudioRemoteTool(
        manifest=StudioToolManifest.model_validate(_manifest(tool_name)),
        dispatcher=Dispatcher(),
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision="revision-1",
    )
    actions = SimpleNamespace(skip_summarization=None)

    asyncio.run(
        tool.run_async(
            args={},
            tool_context=cast(
                ToolContext,
                SimpleNamespace(function_call_id="call-1", actions=actions),
            ),
        )
    )

    assert actions.skip_summarization is None


@pytest.mark.asyncio
async def test_channel_preserves_bounded_content_for_failed_tool_result() -> None:
    sent: list[dict[str, Any]] = []
    connection: _StudioChannelConnection

    async def sender(message: dict[str, Any]) -> None:
        sent.append(message)
        if message["type"] != "tool.call":
            return
        await connection._resolve_tool_result(
            {
                "type": "tool.result",
                "request_id": message["request_id"],
                "run_id": message["run_id"],
                "scope_id": message["scope_id"],
                "catalog_revision": message["catalog_revision"],
                "status": "error",
                "error": "Codex Sandbox 连接中断",
                "content": {
                    "ok": False,
                    "codex_activity": {"events": [{"status": "failed"}]},
                },
            }
        )

    async def run_handler(
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        del payload
        if False:
            yield {}

    connection = _StudioChannelConnection(
        sender=sender,
        run_handler=run_handler,
        reserved_tool_names=set(),
    )
    result = await connection.call_tool(
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision="revision-1",
        manifest=StudioToolManifest.model_validate(_manifest()),
        arguments={"left": 6, "right": 7},
    )

    assert sent[0]["type"] == "tool.call"
    assert result == {
        "ok": False,
        "codex_activity": {"events": [{"status": "failed"}]},
        "status": "error",
        "error": "Codex Sandbox 连接中断",
    }


@pytest.mark.asyncio
async def test_channel_returns_actionable_codex_timeout_without_retrying() -> None:
    sent: list[dict[str, Any]] = []

    async def sender(message: dict[str, Any]) -> None:
        sent.append(message)

    async def run_handler(
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        del payload
        if False:
            yield {}

    connection = _StudioChannelConnection(
        sender=sender,
        run_handler=run_handler,
        reserved_tool_names=set(),
    )
    manifest = _manifest("delegate_to_codex_sandbox")
    manifest["timeout_ms"] = 1

    result = await connection.call_tool(
        run_id="run-1",
        scope_id="scope-1",
        catalog_revision="revision-1",
        manifest=StudioToolManifest.model_validate(manifest),
        arguments={"task": "long review"},
    )

    assert [message["type"] for message in sent] == ["tool.call", "tool.cancel"]
    assert result == {
        "status": "timeout",
        "error": (
            "Codex Sandbox 长任务超过 30 分钟，已停止执行；"
            "请确认当前状态后再决定是否重新提交。"
        ),
    }


@pytest.mark.asyncio
async def test_external_toolset_isolates_concurrent_run_catalogs() -> None:
    toolset = StudioExternalToolset()

    def remote_tool(name: str) -> StudioRemoteTool:
        return StudioRemoteTool(
            manifest=StudioToolManifest.model_validate(_manifest(name)),
            dispatcher=cast(Any, object()),
            run_id=f"run-{name}",
            scope_id=f"scope-{name}",
            catalog_revision=f"revision-{name}",
        )

    async def selected_name(name: str) -> list[str]:
        with bind_studio_tools([remote_tool(name)]):
            await asyncio.sleep(0)
            return [tool.name for tool in await toolset.get_tools()]

    first, second = await asyncio.gather(
        selected_name("studio_first"),
        selected_name("studio_second"),
    )

    assert first == ["studio_first"]
    assert second == ["studio_second"]
    assert await toolset.get_tools() == []


def test_websocket_runs_and_calls_bff_tool_on_the_same_connection() -> None:
    app = FastAPI()
    toolset = StudioExternalToolset()

    async def run_handler(
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        assert payload["session_id"] == "session-1"
        tools = await toolset.get_tools()
        result = await tools[0].run_async(
            args={"left": 6, "right": 7},
            tool_context=cast(ToolContext, None),
        )
        yield {"id": "event-1", "author": "agent", "tool_result": result}

    mount_studio_channel_routes(app=app, run_handler=run_handler)
    tools = [_manifest()]
    revision = catalog_revision(tools)

    with TestClient(app).websocket_connect("/harness/studio-channel/v1") as websocket:
        websocket.send_json(
            {
                "type": "channel.hello",
                "protocol": PROTOCOL_VERSION,
                "studio_instance_id": "studio-1",
            }
        )
        assert websocket.receive_json()["type"] == "channel.ready"

        websocket.send_json(
            {
                "type": "catalog.replace",
                "scope_id": "scope-1",
                "revision": revision,
                "tools": tools,
            }
        )
        assert websocket.receive_json() == {
            "type": "catalog.ack",
            "scope_id": "scope-1",
            "revision": revision,
        }

        websocket.send_json(
            {
                "type": "run.start",
                "request_id": "request-1",
                "run_id": "run-1",
                "scope_id": "scope-1",
                "catalog_revision": revision,
                "payload": {"session_id": "session-1"},
            }
        )
        assert websocket.receive_json() == {
            "type": "run.started",
            "request_id": "request-1",
            "run_id": "run-1",
        }

        tool_call = websocket.receive_json()
        assert tool_call["type"] == "tool.call"
        assert tool_call["run_id"] == "run-1"
        assert tool_call["tool_name"] == "studio_multiply"
        assert tool_call["arguments"] == {"left": 6, "right": 7}
        assert tool_call["function_call_id"] == ""

        websocket.send_json(
            {
                "type": "tool.result",
                "request_id": tool_call["request_id"],
                "run_id": "run-1",
                "scope_id": "scope-1",
                "catalog_revision": revision,
                "status": "success",
                "content": {"product": 42, "executed_by": "studio-bff"},
            }
        )
        run_event = websocket.receive_json()
        assert run_event == {
            "type": "run.event",
            "run_id": "run-1",
            "event": {
                "id": "event-1",
                "author": "agent",
                "tool_result": {"product": 42, "executed_by": "studio-bff"},
            },
        }
        assert websocket.receive_json() == {
            "type": "run.completed",
            "run_id": "run-1",
            "status": "success",
        }


def test_catalog_rejects_agent_tool_name_conflicts() -> None:
    app = FastAPI()

    async def run_handler(
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        del payload
        if False:
            yield {}

    mount_studio_channel_routes(
        app=app,
        run_handler=run_handler,
        reserved_tool_names={"studio_multiply"},
    )
    tools = [_manifest()]

    with TestClient(app).websocket_connect("/harness/studio-channel/v1") as websocket:
        websocket.send_json({"type": "channel.hello", "protocol": PROTOCOL_VERSION})
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "catalog.replace",
                "scope_id": "scope-1",
                "revision": catalog_revision(tools),
                "tools": tools,
            }
        )
        rejection = websocket.receive_json()

    assert rejection["type"] == "catalog.reject"
    assert "conflict" in rejection["error"]


def test_channel_routes_are_promoted_above_an_existing_catchall() -> None:
    app = FastAPI()

    @app.post("/{path:path}")
    async def catchall(path: str) -> dict[str, str]:
        return {"caught": path}

    async def run_handler(
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        del payload
        if False:
            yield {}

    mount_studio_channel_routes(app=app, run_handler=run_handler)
    response = TestClient(app).post(
        "/harness/studio-channel/v1/http-runs",
        json={"protocol": "invalid-on-purpose"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unsupported protocol"}


def test_channel_capability_can_be_advertised_without_enabling_rpc_routes() -> None:
    app = FastAPI()

    async def run_handler(
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        del payload
        if False:
            yield {}

    mount_studio_channel_routes(
        app=app,
        run_handler=run_handler,
        enabled=False,
    )
    client = TestClient(app)

    assert client.get("/harness/studio-channel/v1/capabilities").json() == {
        "enabled": False,
        "protocol": PROTOCOL_VERSION,
        "transports": [],
    }
    assert (
        client.post(
            "/harness/studio-channel/v1/http-runs",
            json={"protocol": PROTOCOL_VERSION},
        ).status_code
        == 404
    )


def test_channel_capability_advertises_supported_transports_when_enabled() -> None:
    app = FastAPI()

    async def run_handler(
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        del payload
        if False:
            yield {}

    mount_studio_channel_routes(app=app, run_handler=run_handler, enabled=True)

    assert TestClient(app).get("/harness/studio-channel/v1/capabilities").json() == {
        "enabled": True,
        "protocol": PROTOCOL_VERSION,
        "transports": ["websocket", "http-sse"],
    }


@pytest.mark.asyncio
async def test_history_projection_summarizes_only_unavailable_tool_parts() -> None:
    plugin = StudioToolHistoryPlugin()
    stale_call = types.Content(
        role="model",
        parts=[
            types.Part.from_function_call(
                name="browser_use",
                args={"task": "private historical input"},
            ),
            types.Part(text="keep this model text"),
        ],
    )
    stale_response = types.Content(
        role="user",
        parts=[
            types.Part.from_function_response(
                name="browser_use",
                response={"result": "private historical output"},
            )
        ],
    )
    current_call = types.Content(
        role="model",
        parts=[types.Part.from_function_call(name="current_tool", args={})],
    )
    internal_call = types.Content(
        role="model",
        parts=[
            types.Part.from_function_call(
                name="transfer_to_agent",
                args={"agent_name": "worker"},
            )
        ],
    )
    source_contents = [stale_call, stale_response, current_call, internal_call]
    source_snapshot = [content.model_copy(deep=True) for content in source_contents]
    request = LlmRequest(
        contents=source_contents,
        tools_dict={
            "current_tool": BaseTool(
                name="current_tool",
                description="Current run tool",
            )
        },
    )

    result = await plugin.before_model_callback(
        callback_context=cast(CallbackContext, object()),
        llm_request=request,
    )

    assert result is None
    assert request.contents is not source_contents
    assert source_contents == source_snapshot
    projected_parts = [
        part for content in request.contents for part in content.parts or []
    ]
    projected_text = "\n".join(part.text or "" for part in projected_parts)
    projected_calls = [
        part.function_call.name
        for part in projected_parts
        if part.function_call is not None
    ]
    assert "browser_use" not in projected_calls
    assert projected_calls == ["current_tool", "transfer_to_agent"]
    assert "keep this model text" in projected_text
    assert "private historical input" not in projected_text
    assert "private historical output" not in projected_text
    assert projected_text.count("not available in this run") == 2


@pytest.mark.asyncio
async def test_unknown_tool_recovery_is_bounded_per_invocation_and_tool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="veadk.integrations.agentkit.studio_channel.history",
    )
    plugin = StudioToolHistoryPlugin()
    missing_tool = BaseTool(name="browser_use", description="Tool not found")
    context = SimpleNamespace(invocation_id="invocation-1")
    error = ValueError("Tool 'browser_use' not found.\nAvailable tools:")

    first = await plugin.on_tool_error_callback(
        tool=missing_tool,
        tool_args={"task": "open example.com"},
        tool_context=cast(ToolContext, context),
        error=error,
    )
    repeated = await plugin.on_tool_error_callback(
        tool=missing_tool,
        tool_args={"task": "open example.com again"},
        tool_context=cast(ToolContext, context),
        error=error,
    )
    another_tool = await plugin.on_tool_error_callback(
        tool=BaseTool(name="old_search", description="Tool not found"),
        tool_args={},
        tool_context=cast(ToolContext, context),
        error=ValueError("Tool 'old_search' not found.\nAvailable tools:"),
    )

    assert first == {
        "status": "unavailable",
        "reason_code": "TOOL_NOT_AVAILABLE_IN_CURRENT_RUN",
        "message": (
            "This tool is not available in the current run. Continue without "
            "it, or ask the user to start a new run that enables the capability."
        ),
    }
    assert repeated is None
    assert another_tool is not None

    await plugin.after_run_callback(
        invocation_context=cast(
            InvocationContext,
            SimpleNamespace(invocation_id="invocation-1"),
        )
    )
    after_cleanup = await plugin.on_tool_error_callback(
        tool=missing_tool,
        tool_args={},
        tool_context=cast(ToolContext, context),
        error=error,
    )
    assert after_cleanup == first
    recovered = [
        record
        for record in caplog.records
        if getattr(record, "browser_event", "") == "browser_unknown_tool_recovered"
    ]
    assert len(recovered) == 2
    assert all(
        record.reason_code == "TOOL_NOT_AVAILABLE_IN_CURRENT_RUN"
        for record in recovered
    )
    assert "open example.com" not in caplog.text


@pytest.mark.asyncio
async def test_history_plugin_does_not_mask_real_tool_errors() -> None:
    plugin = StudioToolHistoryPlugin()

    result = await plugin.on_tool_error_callback(
        tool=BaseTool(name="browser_use", description="Managed browser"),
        tool_args={},
        tool_context=cast(
            ToolContext,
            SimpleNamespace(invocation_id="invocation-1"),
        ),
        error=RuntimeError("browser backend failed"),
    )

    assert result is None


@pytest.mark.asyncio
async def test_adk_runner_recovers_unknown_tool_without_mutating_session() -> None:
    model = _UnknownToolThenAnswerModel()
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="studio-agent",
        user_id="user-1",
        session_id="session-1",
    )
    runner = AdkRunner(
        agent=AdkAgent(name="studio_agent", model=model),
        app_name="studio-agent",
        plugins=[StudioToolHistoryPlugin()],
        session_service=session_service,
    )

    events = [
        event
        async for event in runner.run_async(
            user_id="user-1",
            session_id="session-1",
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="Open example.com")],
            ),
        )
    ]

    assert any(
        part.text == "Continued without the unavailable tool."
        for event in events
        for part in (event.content.parts if event.content else []) or []
    )
    unavailable_responses = [
        response.response
        for event in events
        for response in event.get_function_responses()
        if response.name == "browser_use"
    ]
    assert unavailable_responses == [
        {
            "status": "unavailable",
            "reason_code": "TOOL_NOT_AVAILABLE_IN_CURRENT_RUN",
            "message": (
                "This tool is not available in the current run. Continue "
                "without it, or ask the user to start a new run that enables "
                "the capability."
            ),
        }
    ]

    projected_parts = [
        part for content in model._requests[-1] for part in content.parts or []
    ]
    assert not any(part.function_call is not None for part in projected_parts)
    assert not any(part.function_response is not None for part in projected_parts)

    persisted = await session_service.get_session(
        app_name="studio-agent",
        user_id="user-1",
        session_id="session-1",
    )
    assert persisted is not None
    assert any(event.get_function_calls() for event in persisted.events)
    assert any(event.get_function_responses() for event in persisted.events)
