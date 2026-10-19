"""Embedding the public App must not build another environment runtime."""

import importlib
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from uvicorn.importer import import_from_string


def test_class_import_does_not_construct_environment_agent():
    program = """
import socket

def deny_network(*args, **kwargs):
    raise AssertionError("unexpected startup network")
socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.getaddrinfo = deny_network
import veadk.cloud.harness_app.utils as utils

def deny_default_agent(*args, **kwargs):
    raise AssertionError("class import initialized default agent")
utils.init_harness_agent = deny_default_agent
from veadk.cloud.harness_app.app import HarnessApp
assert callable(HarnessApp)
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "TMPDIR", "SYSTEMROOT", "PYTHONPATH"}
    }
    env.update(
        PYTHON_DOTENV_DISABLED="1",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        LITELLM_TELEMETRY="False",
        OTEL_SDK_DISABLED="true",
        MODEL_AGENT_API_KEY="offline-fixture-only",
        MODEL_AGENT_API_BASE="https://model.invalid/v1",
        MODEL_AGENT_PROVIDER="openai",
    )
    result = subprocess.run(
        [sys.executable, "-c", program], env=env, capture_output=True, timeout=60
    )
    # Keep all SDK diagnostics out of the test report.
    assert result.returncode == 0, "public App import unexpectedly initializes runtime"


def test_legacy_asgi_attributes_share_explicit_default(monkeypatch):
    module = importlib.import_module("veadk.cloud.harness_app.app")
    calls = []
    runtime = SimpleNamespace(app=object())

    def build():
        calls.append(True)
        return runtime

    module._cached_default_harness_app.cache_clear()
    monkeypatch.setattr(module, "create_default_harness_app", build)
    try:
        assert module.app is runtime.app
        assert module.harness_app is runtime
        assert module.get_default_harness_app() is runtime
        assert import_from_string("veadk.cloud.harness_app.app:app") is runtime.app
        assert len(calls) == 1
    finally:
        module._cached_default_harness_app.cache_clear()


def test_explicit_factory_uses_current_environment_and_supplied_services(monkeypatch):
    module = importlib.import_module("veadk.cloud.harness_app.app")
    utils = importlib.import_module("veadk.cloud.harness_app.utils")
    agent, memory = object(), object()
    calls = []

    def assemble():
        calls.append(True)
        return agent, memory

    def app_factory(actual_agent, actual_memory, name, max_llm_calls):
        assert actual_agent is agent
        assert actual_memory is memory
        return SimpleNamespace(name=name, max_llm_calls=max_llm_calls)

    monkeypatch.setattr(utils, "init_harness_agent", assemble)
    monkeypatch.setattr(module, "HarnessApp", app_factory)
    monkeypatch.setenv("HARNESS_NAME", "embedded-test")
    monkeypatch.setenv("MAX_LLM_CALLS", "37")
    first = module.create_default_harness_app()
    second = module.create_default_harness_app()
    assert first is not second
    assert first.name == second.name == "embedded-test"
    assert first.max_llm_calls == second.max_llm_calls == 37
    assert len(calls) == 2


def test_concurrent_default_access_constructs_only_one_app(monkeypatch):
    module = importlib.import_module("veadk.cloud.harness_app.app")
    calls = []

    def build():
        calls.append(True)
        time.sleep(0.05)
        return SimpleNamespace(app=object())

    module._cached_default_harness_app.cache_clear()
    monkeypatch.setattr(module, "create_default_harness_app", build)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            apps = list(pool.map(lambda _: module.get_default_harness_app(), range(4)))
        assert len(calls) == 1
        assert all(app is apps[0] for app in apps)
    finally:
        module._cached_default_harness_app.cache_clear()
