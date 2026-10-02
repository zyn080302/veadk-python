"""Reversible native tool encoding for function-only Responses providers.

This changes wire schema only. Codex still dispatches every call and records
every result. Hosted tools cannot be implemented by a schema conversion and
are rejected explicitly rather than silently removed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re


async def adapt_sse(lines, adapter):
    """Decode whole SSE records, including multiline data, without buffering prose."""
    data = []
    async for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            payload = "\n".join(data)
            data.clear()
            if payload == "[DONE]":
                yield b"data: [DONE]\n\n"
                continue
            for event in adapter.event(json.loads(payload)):
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
    if data:
        raise ValueError("Incomplete Responses SSE record")


class ToolWireAdapter:
    def __init__(self):
        self._aliases = {}
        self._custom_ids = set()

    def business_names(self, tools, executors):
        """Map advertised names to this MCP server's exact registered tools."""
        result = {}
        for tool in tools:
            wire_name = tool.get("name")
            namespace, name, _ = self._aliases.get(wire_name, (None, wire_name, False))
            for business_name in executors:
                if name == f"mcp__veadk__{business_name}" or (
                    namespace == "mcp__veadk" and name == business_name
                ):
                    result[wire_name] = business_name
        return result

    def _alias(self, name, namespace, custom=False):
        if not namespace and not custom:
            return name
        identity = (namespace, name, custom)
        readable = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:32]
        alias = (
            "veadk_"
            + readable
            + "_"
            + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]
        )
        previous = self._aliases.setdefault(alias, identity)
        if previous != identity:
            raise ValueError("Native tool alias collision")
        return alias

    def request(self, body):
        body = copy.deepcopy(body)
        tools = []
        raw_tools = body.get("tools", [])
        plain_names = {
            tool.get("name") for tool in raw_tools if tool.get("type") == "function"
        }

        def add(tool, namespace=None):
            kind = tool.get("type")
            if kind == "namespace":
                for child in tool.get("tools", []):
                    add(child, tool["name"])
                return
            if kind == "tool_search" and tool.get("execution") == "client":
                alias = self._alias("tool_search", None, "search")
                if alias in plain_names:
                    raise ValueError("Native tool alias collides with a function name")
                tools.append(
                    {
                        "type": "function",
                        "name": alias,
                        "description": tool.get(
                            "description", "Search available tools."
                        ),
                        "parameters": tool["parameters"],
                    }
                )
                return
            if kind not in {"function", "custom"}:
                raise ValueError(
                    f"Function-only Responses cannot represent hosted tool {kind!r}"
                )
            alias = self._alias(tool["name"], namespace, kind == "custom")
            if alias in self._aliases and alias in plain_names:
                raise ValueError("Native tool alias collides with a function name")
            if kind == "custom":
                spec = {
                    "type": "function",
                    "name": alias,
                    "description": tool.get("description", "")
                    + "\nSupply the native tool input verbatim as the input string.\n"
                    + json.dumps(
                        tool.get("format", {"type": "text"}), ensure_ascii=False
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"input": {"type": "string"}},
                        "required": ["input"],
                        "additionalProperties": False,
                    },
                }
            else:
                spec = {**tool, "name": alias}
            tools.append(spec)

        for tool in raw_tools:
            add(tool)
        if "tools" in body:
            body["tools"] = tools
        for item in body.get("input", []):
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind in {"tool_search_call", "tool_search_output"}:
                if item.get("execution") != "client" or not item.get("call_id"):
                    raise ValueError(
                        "Function-only Responses cannot represent server tool_search"
                    )
                item.pop("execution")
                if kind == "tool_search_call":
                    item["type"] = "function_call"
                    item["name"] = self._alias("tool_search", None, "search")
                    item["arguments"] = json.dumps(
                        item["arguments"], ensure_ascii=False
                    )
                else:
                    # Discovered tool declarations are native tool-search
                    # results. Advertise that same set using function schema
                    # so the provider can call them on the next request.
                    start = len(tools)
                    for found in item.pop("tools"):
                        add(found)
                    item["type"] = "function_call_output"
                    item["output"] = json.dumps(
                        {"tools": tools[start:]}, ensure_ascii=False
                    )
            elif kind in {"function_call", "custom_tool_call"}:
                item["name"] = self._alias(
                    item["name"],
                    item.pop("namespace", None),
                    kind == "custom_tool_call",
                )
                if kind == "custom_tool_call":
                    item["type"] = "function_call"
                    item["arguments"] = json.dumps(
                        {"input": item.pop("input")}, ensure_ascii=False
                    )
            elif kind == "custom_tool_call_output":
                item["type"] = "function_call_output"
            elif kind == "function_call_output":
                item.pop("namespace", None)
        choice = body.get("tool_choice")
        if isinstance(choice, dict) and choice.get("name"):
            custom = choice.get("type") == "custom"
            choice["name"] = self._alias(
                choice["name"], choice.pop("namespace", None), custom
            )
            if custom:
                choice["type"] = "function"
        elif isinstance(choice, dict) and choice.get("type") == "tool_search":
            body["tool_choice"] = {
                "type": "function",
                "name": self._alias("tool_search", None, "search"),
            }
        if "tools" in body:
            # A discovered schema can also be present in the top-level list.
            unique = {}
            for tool in tools:
                previous = unique.setdefault(tool["name"], tool)
                if previous != tool:
                    raise ValueError("Conflicting native tool declarations")
            body["tools"] = list(unique.values())
        return body

    def _item(self, original, *, started=False):
        item = copy.deepcopy(original)
        identity = self._aliases.get(item.get("name"))
        if not identity or item.get("type") != "function_call":
            return item
        namespace, name, custom = identity
        item["name"] = name
        if namespace:
            item["namespace"] = namespace
        if custom == "search":
            if item.get("id"):
                self._custom_ids.add(item["id"])
            item.pop("name")
            raw = item.pop("arguments", "")
            try:
                arguments = {} if started else json.loads(raw)
            except (ValueError, TypeError):
                raise ValueError("Tool search requires JSON arguments") from None
            if not isinstance(arguments, dict):
                raise ValueError("Tool search requires JSON object arguments")
            item.update(
                type="tool_search_call", execution="client", arguments=arguments
            )
        elif custom:
            if item.get("id"):
                self._custom_ids.add(item["id"])
            raw = item.pop("arguments", "")
            if started:
                native_input = ""
            else:
                try:
                    args = json.loads(raw)
                except (ValueError, TypeError):
                    raise ValueError("Custom tool requires one string input") from None
                if (
                    not isinstance(args, dict)
                    or set(args) != {"input"}
                    or not isinstance(args["input"], str)
                ):
                    raise ValueError("Custom tool requires one string input")
                native_input = args["input"]
            item.update(type="custom_tool_call", input=native_input)
        return item

    def event(self, original):
        event = copy.deepcopy(original)
        kind = event.get("type", "")
        if isinstance(event.get("item"), dict):
            event["item"] = self._item(event["item"], started=kind.endswith(".added"))
        if event.get("item_id") in self._custom_ids and kind.startswith(
            "response.function_call_arguments."
        ):
            # Wait for the complete JSON argument before decoding the string.
            # Dispatch remains driven by the full output_item.done event.
            return []
        if isinstance(event.get("response"), dict):
            response = event["response"]
            if isinstance(response.get("output"), list):
                response["output"] = [self._item(item) for item in response["output"]]
        return [event]
