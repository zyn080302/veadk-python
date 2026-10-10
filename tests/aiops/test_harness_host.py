# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

"""A fixed Harness image serves the configured AI OPS application."""

from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastapi import FastAPI, Request
from starlette.routing import Mount
from starlette.responses import PlainTextResponse

from tests.aiops.test_harness_configuration import document
from veadk.aiops.harness.host import prepare_server


@pytest.mark.asyncio
async def test_configuration_readback_precedes_root_mount_and_never_resolves_secrets(
    monkeypatch,
):
    captured = {}
    app = FastAPI()

    @app.post("/invoke")
    async def invoke(request: Request):
        return {"session_id": request.headers.get("session_id")}

    async def fallback(scope, receive, send):
        await PlainTextResponse("fallback", status_code=404)(scope, receive, send)

    app.router.routes.append(Mount("/", app=fallback))

    def create_server(config, plugins, *, agent):
        captured.update(config=config, plugins=plugins, agent=agent)
        app.state.aiops_agent = agent
        return app

    monkeypatch.setattr("veadk.aiops.hosting.create_server", create_server)
    monkeypatch.setattr(
        "veadk.aiops.harness.host.build_agent", lambda **kw: SimpleNamespace(**kw)
    )
    config = document()
    config["agent"]["name"] = "example"
    raw = yaml.safe_dump(config)
    server = await prepare_server(
        raw,
        environment={
            "MODEL_KEY": "fixture-secret",
            "METRICS_KEY": "fixture-key",
            "LOGS_KEY": "fixture-key",
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server), base_url="http://test"
    ) as client:
        readback = await client.get("/agent_config")
        assert readback.text == raw
        assert "fixture-secret" not in readback.text
        assert readback.headers["cache-control"] == "no-store"
        assert (await client.get("/healthz")).json() == {"status": "ready"}
        response = await client.post("/invoke", json={})
        assert (
            response.json()["session_id"] == response.headers["x-agentkit-session-id"]
        )
        assert (
            await client.post("/invoke", headers={"session_id": "original"}, json={})
        ).json()["session_id"] == "original"
    assert captured["config"].customer_instruction == "客户附加规则"
    assert captured["config"].studio_enabled is True
    assert len(captured["plugins"]) == 1


@pytest.mark.asyncio
async def test_configuration_failure_does_not_load_engine(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid configuration must not load engine")

    monkeypatch.setattr("veadk.aiops.hosting.create_server", forbidden)
    with pytest.raises(ValueError):
        await prepare_server("not valid", environment={})
