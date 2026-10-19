"""Invocation-scoped native ADK tools with detached state and ordered publication."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import time

import anyio
from uuid import uuid4

from .dispatch import _LocalToolFailure, _ToolResult


def _json_copy(value):
    # Validate before Pydantic's permissive serializer can stringify objects.
    def check(item):
        if type(item) in (str, int, float, bool, type(None)):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child)
            return
        raise ValueError

    try:
        check(value)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 1024 * 1024:
            raise ValueError
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError):
        raise _LocalToolFailure("unsupported_native_json") from None


def _schema(value):
    def normalize(node):
        if isinstance(node, list):
            return [normalize(item) for item in node]
        if not isinstance(node, dict):
            return node
        result = {}
        for key, item in node.items():
            if key in {"title", "description"}:
                continue
            if key in {
                "properties",
                "patternProperties",
                "$defs",
                "definitions",
                "dependentSchemas",
                "dependencies",
            }:
                result[key] = {name: normalize(schema) for name, schema in item.items()}
            elif key in {
                "items",
                "additionalProperties",
                "not",
                "if",
                "then",
                "else",
                "contains",
                "propertyNames",
                "unevaluatedProperties",
                "unevaluatedItems",
                "allOf",
                "anyOf",
                "oneOf",
                "prefixItems",
            }:
                result[key] = normalize(item)
            else:
                result[key] = copy.deepcopy(item)
        return result

    value = normalize(value)
    if value.get("type") == "object":
        value.setdefault("additionalProperties", False)
    return value


def _collect(agent, declarations):
    from google.adk.models.lite_llm import _function_declaration_to_tool_param
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.function_tool import FunctionTool

    result = {}
    expected = {item.name: item for item in declarations}
    for entry in agent.tools:
        if not isinstance(entry, BaseTool):
            if not inspect.iscoroutinefunction(entry):
                raise _LocalToolFailure("unsupported_native_tool")
            entry = FunctionTool(entry)
        if (
            not inspect.iscoroutinefunction(entry.run_async)
            or getattr(entry, "is_long_running", False)
            or getattr(entry, "_defers_response", False)
            or (
                isinstance(entry, FunctionTool)
                and not inspect.iscoroutinefunction(entry.func)
            )
        ):
            raise _LocalToolFailure("unsupported_native_tool")
        try:
            declaration = entry._get_declaration()
            spec = _function_declaration_to_tool_param(declaration)["function"]
            name = spec["name"]
            parameters = spec.get("parameters", {"type": "object", "properties": {}})
        except Exception:
            raise _LocalToolFailure("unsupported_native_declaration") from None
        if (
            name != entry.name
            or name in result
            or name not in expected
            or _schema(parameters) != _schema(expected[name].input_schema)
            or expected[name].long_running
        ):
            raise _LocalToolFailure("native_catalog_mismatch")
        result[name] = entry
    if set(result) != set(expected):
        raise _LocalToolFailure("native_catalog_mismatch")
    return result


class _NativeToolBridge:
    def __init__(self, agent, ctx, declarations):
        self.tools = _collect(agent, declarations)
        self._ctx = ctx
        self._state = _json_copy(ctx.session.state)
        self._lock = asyncio.Lock()
        self._closed = False
        self.sink = None
        self.executors = {
            name: self._executor(tool) for name, tool in self.tools.items()
        }

    def close(self):
        self._closed = True

    def _check_active(self):
        if self._closed or anyio.current_effective_deadline() <= time.monotonic():
            raise _LocalToolFailure("native_tool_closed")

    def _executor(self, tool):
        async def execute(args, request_id):
            from google.adk.events import Event, EventActions
            from google.adk.flows.llm_flows import functions
            from google.genai import types

            async with self._lock:
                self._check_active()
                # Only local session data is cloned. Services remain server-owned;
                # this is state isolation, not isolation of arbitrary Python code.
                session = self._ctx.session.model_copy(deep=True)
                session.state = copy.deepcopy(self._state)
                ctx = self._ctx.model_copy(update={"session": session})
                call_id = uuid4().hex
                identity = dict(
                    author=ctx.agent.name,
                    invocation_id=ctx.invocation_id,
                    branch=ctx.branch,
                )
                call_event = Event(
                    **identity,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    id=call_id, name=tool.name, args=args
                                )
                            )
                        ],
                    ),
                )
                try:
                    response = await functions.handle_function_calls_async(
                        ctx, call_event, {tool.name: tool}
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    response = None
                    payload, delta = {"error": "tool_execution_failed"}, {}
                    status, error = "error", "tool_execution_failed"
                else:
                    self._check_active()
                    if response is None:
                        raise _LocalToolFailure("unsupported_native_response")
                    actions = response.actions
                    if any(
                        getattr(actions, key)
                        for key in type(actions).model_fields
                        if key != "state_delta"
                    ):
                        raise _LocalToolFailure("unsupported_native_actions")
                    delta = _json_copy(actions.state_delta)
                    if any(":" in key and not key.startswith("temp:") for key in delta):
                        raise _LocalToolFailure("unsupported_native_state")
                    responses = response.get_function_responses()
                    if (
                        len(responses) != 1
                        or responses[0].id != call_id
                        or responses[0].name != tool.name
                        or response.long_running_tool_ids
                        or len(response.content.parts) != 1
                        or any(
                            getattr(responses[0], key) is not None
                            for key in type(responses[0]).model_fields
                            if key not in {"id", "name", "response"}
                        )
                    ):
                        raise _LocalToolFailure("unsupported_native_response")
                    payload = _json_copy(responses[0].response)
                    status, error = "success", ""
                self._check_active()
                response_event = Event(
                    **identity,
                    content=types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=call_id, name=tool.name, response=payload
                                )
                            )
                        ],
                    ),
                    actions=EventActions(
                        state_delta={
                            k: v for k, v in delta.items() if not k.startswith("temp:")
                        }
                    ),
                )
                await self.sink(request_id, (call_event, response_event))
                self._check_active()
                self._state.update(copy.deepcopy(delta))
                return _ToolResult(payload, status, error)

        return execute
