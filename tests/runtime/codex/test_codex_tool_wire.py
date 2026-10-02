"""Function-only provider adaptation must preserve native tool semantics."""

import json

import pytest

from veadk.runtime.codex.tool_wire import ToolWireAdapter


def test_namespace_roundtrip_preserves_dispatch_and_history():
    original = {
        "tools": [
            {
                "type": "namespace",
                "name": "mcp__veadk",
                "tools": [
                    {
                        "type": "function",
                        "name": "echo",
                        "parameters": {"type": "object"},
                    }
                ],
            }
        ],
        "input": [
            {
                "type": "function_call",
                "namespace": "mcp__veadk",
                "name": "echo",
                "arguments": "{}",
                "call_id": "c",
            },
            {"type": "function_call_output", "call_id": "c", "output": "ok"},
        ],
    }
    untouched = json.dumps(original, sort_keys=True)
    adapter = ToolWireAdapter()
    outbound = adapter.request(original)
    tool = outbound["tools"][0]
    assert tool["type"] == "function"
    assert "namespace" not in outbound["input"][0]
    assert outbound["input"][0]["name"] == tool["name"]
    event = {
        "type": "response.output_item.done",
        "output_index": 0,
        "item": {
            "type": "function_call",
            "name": tool["name"],
            "arguments": "{}",
            "call_id": "c",
        },
    }
    decoded = adapter.event(event)[0]["item"]
    assert decoded["namespace"] == "mcp__veadk"
    assert decoded["name"] == "echo"
    assert decoded["call_id"] == "c"
    assert json.dumps(original, sort_keys=True) == untouched


def test_custom_tool_roundtrip_preserves_patch_bytes_and_result():
    patch = "*** Begin Patch\n*** Add File: test.txt\n+test\n*** End Patch\n"
    adapter = ToolWireAdapter()
    outbound = adapter.request(
        {
            "tools": [
                {
                    "type": "custom",
                    "name": "apply_patch",
                    "format": {
                        "type": "grammar",
                        "syntax": "lark",
                        "definition": "start: /.+/",
                    },
                }
            ],
            "input": [
                {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "input": patch,
                    "call_id": "c",
                },
                {"type": "custom_tool_call_output", "output": "ok", "call_id": "c"},
            ],
        }
    )
    tool = outbound["tools"][0]
    assert tool["parameters"]["properties"]["input"]["type"] == "string"
    assert "start: /.+/" in tool["description"]
    assert json.loads(outbound["input"][0]["arguments"])["input"] == patch
    assert outbound["input"][1]["type"] == "function_call_output"
    done = {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "name": tool["name"],
            "arguments": json.dumps({"input": patch}),
            "call_id": "c",
        },
    }
    item = adapter.event(done)[0]["item"]
    assert item["type"] == "custom_tool_call"
    assert item["input"] == patch
    assert item["name"] == "apply_patch"
    assert "arguments" not in item


def test_unsupported_hosted_tools_and_malformed_custom_calls_fail_explicitly():
    with pytest.raises(ValueError, match="web_search"):
        ToolWireAdapter().request({"tools": [{"type": "web_search"}]})
    adapter = ToolWireAdapter()
    tool = adapter.request({"tools": [{"type": "custom", "name": "patch"}]})["tools"][0]
    with pytest.raises(ValueError, match="string input"):
        adapter.event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "name": tool["name"],
                    "arguments": '{"input":123}',
                },
            }
        )


def test_client_tool_search_preserves_dispatch_and_discovered_schemas():
    adapter = ToolWireAdapter()
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    tool = {"type": "tool_search", "execution": "client", "parameters": schema}
    discovered = {
        "type": "namespace",
        "name": "mcp__docs",
        "tools": [{"type": "function", "name": "lookup", "parameters": schema}],
    }
    body = {
        "tools": [tool],
        "input": [
            {
                "type": "tool_search_call",
                "call_id": "search-1",
                "execution": "client",
                "arguments": {"query": "docs"},
            },
            {
                "type": "tool_search_output",
                "call_id": "search-1",
                "execution": "client",
                "status": "completed",
                "tools": [discovered],
            },
        ],
    }
    untouched = json.dumps(body, sort_keys=True)
    outbound = adapter.request(body)
    search = outbound["tools"][0]
    assert search["type"] == "function" and search["parameters"] == schema
    assert outbound["input"][0]["name"] == search["name"]
    assert json.loads(outbound["input"][0]["arguments"]) == {"query": "docs"}
    result = outbound["input"][1]
    assert result["type"] == "function_call_output" and result["call_id"] == "search-1"
    found = json.loads(result["output"])["tools"][0]
    assert found in outbound["tools"] and found["type"] == "function"
    decoded = adapter.event(
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": search["name"],
                "arguments": '{"query":"docs"}',
                "call_id": "search-2",
                "id": "item-2",
            },
        }
    )[0]["item"]
    assert decoded == {
        "type": "tool_search_call",
        "arguments": {"query": "docs"},
        "execution": "client",
        "call_id": "search-2",
        "id": "item-2",
    }
    assert json.dumps(body, sort_keys=True) == untouched


def test_server_tool_search_is_not_disguised_as_client_execution():
    with pytest.raises(ValueError, match="tool_search"):
        ToolWireAdapter().request(
            {"tools": [{"type": "tool_search", "execution": "server"}]}
        )
