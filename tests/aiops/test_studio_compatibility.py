# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

"""Shipped optional Studio hooks remain independent of the private Core."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from google.adk.agents import LlmAgent
from google.adk.apps import App

from veadk.cli.legacy_runtime_recovery import _SITECUSTOMIZE
from veadk.integrations.agentkit.app import _add_introspection_routes


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("VEADK_STUDIO_SKILL_OVERLAY", str(tmp_path))
    monkeypatch.setattr(App, "__init__", App.__init__)
    namespace = {}
    exec(compile(_SITECUSTOMIZE, "<generated-overlay>", "exec"), namespace)
    return namespace["_replace_mcp"]


def test_overlay_preserves_factory_owned_tools(overlay):
    calls = []
    wrapped = object()
    agent = SimpleNamespace(
        name="example",
        tools=[wrapped],
        sub_agents=[],
        _veadk_studio_mcp_overlay_handler=calls.append,
    )
    selected = [
        {"name": "inventory", "transport": "http", "url": "https://example.invalid/mcp"}
    ]
    overlay(agent, {"example": selected})
    assert calls == [selected]
    assert agent.tools == [wrapped]


@pytest.mark.parametrize(
    "handler",
    [42, lambda _: (_ for _ in ()).throw(RuntimeError("configuration changed"))],
)
def test_overlay_rejects_invalid_or_stale_handler(overlay, handler):
    agent = SimpleNamespace(
        name="example",
        tools=[],
        sub_agents=[],
        _veadk_studio_mcp_overlay_handler=handler,
    )
    with pytest.raises(RuntimeError):
        overlay(agent, {"example": []})


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", [None, False, True])
async def test_instruction_editor_is_explicit_and_does_not_evaluate_instruction(marker):
    def instruction(context):
        pytest.fail("introspection must not evaluate private instructions")

    agent = LlmAgent(name="example", instruction=instruction)
    if marker is not None:
        agent._studio_instruction_extension = marker
    app = FastAPI()
    _add_introspection_routes(app, agent, {})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://offline"
    ) as client:
        response = await client.get("/web/agent-info/example")
    assert response.status_code == 200
    info = response.json()
    assert ("instructionExtension" in info) == (marker is True)
    if marker is True:
        assert info["instructionExtension"] is True
    assert info["graph"]["instruction"] == ""
