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

"""Fixed-configuration AI OPS Harness, using the standard SDK application."""

import os
import re
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from veadk.aiops.config import AgentConfig
from veadk.aiops.harness.configuration import (
    HarnessConfigurationError,
    load_configuration,
)
from veadk.aiops.plugin import AgentPlugin


def build_agent(**kwargs):
    from veadk import Agent

    return Agent(**kwargs)


def _mcp_toolsets(connections):
    from google.adk.tools.mcp_tool.mcp_session_manager import (
        SseConnectionParams,
        StreamableHTTPConnectionParams,
    )
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

    toolsets = []
    for index, item in enumerate(connections, start=1):
        headers = {"Authorization": "Bearer " + item.api_key} if item.api_key else {}
        connection_type = (
            SseConnectionParams
            if item.url.rstrip("/").endswith("/sse")
            else StreamableHTTPConnectionParams
        )
        toolsets.append(
            McpToolset(
                connection_params=connection_type(url=item.url, headers=headers),
                tool_name_prefix=f"mcp_{index}",
            )
        )
    return toolsets


async def prepare_server(
    source: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    config: AgentConfig | None = None,
    plugins: Sequence[AgentPlugin] = (),
    mcp_builder=None,
):
    """Prepare selected resources, then expose an immutable configuration.

    Model/MCP credentials remain private. Trusted image code may supply domain
    plugins and a typed MCP builder; YAML cannot import executable code.
    """
    from veadk.aiops import hosting
    from veadk.aiops.harness.resources import prepare_resources

    environment = dict(os.environ if environment is None else environment)
    if environment.get("AGENT_RUNTIME_MODE") == "shared":
        raise HarnessConfigurationError("AI OPS Harness requires fixed configuration")
    prepared = load_configuration(
        environment.get("AGENT_CONFIG", "") if source is None else source
    )
    resolved = prepared.resolve(environment)
    selection = prepared.agent
    name = environment.get("HARNESS_NAME") or re.sub(
        r"[^A-Za-z0-9_]", "_", selection.name
    )
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name == "user":
        raise HarnessConfigurationError(
            "Harness execution name must be an Agent identifier"
        )
    # YAML is the authoritative editable layer; no stale environment override.
    settings = (config or AgentConfig()).model_copy(
        update={
            "name": name,
            "description": selection.description,
            "model_name": selection.model,
            "customer_instruction": selection.instruction,
            "studio_enabled": True,
            "instruction_source": "harness_config",
        }
    )
    resources = await prepare_resources(resolved)
    try:
        selected = {path.name: path for path in resources.directories}
        if len(selected) != len(resources.directories):
            raise HarnessConfigurationError("Selected Skills have duplicate names")
        domain = []
        for plugin in plugins:
            directories = tuple(
                selected.pop(path.name)
                for path in plugin.skill_directories
                if path.name in selected
            )
            domain.append(
                replace(plugin, skill_directories=directories, mcp_factory=None)
            )
        builder = mcp_builder or _mcp_toolsets
        domain.append(
            AgentPlugin(
                name="studio_harness_configuration",
                skill_directories=tuple(selected.values()),
                mcp_factory=lambda context: builder(resolved.mcp_servers),
            )
        )
        agent = build_agent(
            name=name,
            description=selection.description,
            instruction="",
            model_name=selection.model,
            model_provider=resolved.model_provider,
            model_api_base=resolved.model_api_base,
            model_api_key=resolved.model_api_key,
        )
        server = hosting.create_server(settings, tuple(domain), agent=agent)
    except BaseException:
        resources.close()
        raise

    original_lifespan = server.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original_lifespan(app) as state:
                yield state
        finally:
            resources.close()

    server.router.lifespan_context = lifespan

    async def read_configuration(request):
        return Response(
            prepared.public_yaml,
            media_type="application/yaml",
            headers={"Cache-Control": "no-store"},
        )

    async def health(request):
        return JSONResponse({"status": "ready"})

    # Insert before AgentKit's catch-all A2A mount.
    server.router.routes[0:0] = [
        Route("/agent_config", read_configuration, methods=["GET"]),
        Route("/healthz", health, methods=["GET"]),
    ]

    @server.middleware("http")
    async def invoke_session(request, call_next):
        generated = None
        if request.url.path == "/invoke" and not request.headers.get("session_id"):
            generated = str(uuid4())
            request.scope["headers"] = [
                (k, v)
                for k, v in request.scope["headers"]
                if k.lower() != b"session_id"
            ] + [(b"session_id", generated.encode())]
        response = await call_next(request)
        if generated:
            response.headers["X-Agentkit-Session-Id"] = generated
        return response

    return server
