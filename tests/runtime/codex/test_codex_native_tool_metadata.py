"""MCP metadata survives callback rebuilds without leaking into function specs."""

import asyncio

from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpTool
from mcp.types import Tool, ToolAnnotations

from veadk.runtime.codex.tools_bridge import (
    build_executable_tools,
    native_mcp_tool_specs,
    sync_bundle_to_tools_dict,
)


def test_callback_rebuild_preserves_metadata_and_plain_function_specs():
    async def check():
        schema = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }
        annotation = ToolAnnotations(
            title="synthetic",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
        first = McpTool(
            mcp_tool=Tool(
                name="first",
                description="Synthetic first",
                inputSchema=schema,
                annotations=annotation,
            ),
            mcp_session_manager=object(),
        )
        replacement = McpTool(
            mcp_tool=Tool(
                name="replacement",
                description="Synthetic replacement",
                inputSchema=schema,
                annotations=ToolAnnotations(readOnlyHint=False),
            ),
            mcp_session_manager=object(),
        )
        agent = LlmAgent(name="metadata", tools=[first])
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="metadata", user_id="u")
        ctx = InvocationContext(
            invocation_id="metadata",
            agent=agent,
            session=session,
            session_service=sessions,
        )
        bundle = await build_executable_tools(agent, ctx)
        plain = dict(bundle.specs[0])
        native = native_mcp_tool_specs(bundle)
        assert native[0]["annotations"] == annotation.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        assert bundle.specs == [plain] and "annotations" not in plain
        native[0]["annotations"]["readOnlyHint"] = False
        assert first.raw_mcp_tool.annotations.readOnlyHint is True
        sync_bundle_to_tools_dict(bundle, {replacement.name: replacement}, ctx)
        rebuilt = native_mcp_tool_specs(bundle)
        assert len(rebuilt) == 1 and rebuilt[0]["name"] == "replacement"
        assert rebuilt[0]["annotations"]["readOnlyHint"] is False
        assert "annotations" not in bundle.specs[0]
        assert rebuilt[0]["parameters"] == plain["parameters"]

    asyncio.run(check())
