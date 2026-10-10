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

"""Provider extensions must follow the lifetime of the real runtime stream."""

import asyncio
from contextlib import aclosing, asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from veadk.runtime.codex.config import CodexRuntimeConfig
from veadk.runtime.codex.provider_extension import CodexProviderEndpoint
from veadk.runtime.codex.runtime import CodexRuntime


def agent(factory=None):
    return SimpleNamespace(
        codex_runtime_config=CodexRuntimeConfig(provider_factory=factory)
    )


def test_factory_is_programmatic_and_not_serialized():
    def factory(agent, context):
        return None

    config = CodexRuntimeConfig(provider_factory=factory)
    assert "provider_factory" not in config.model_dump()
    assert "provider_factory" not in config.model_dump_json()
    assert "provider_factory" not in repr(config)
    assert config.provider_factory is factory
    with pytest.raises(ValidationError):
        CodexRuntimeConfig(provider_factory="import.module:execute")


@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ["complete", "error", "disconnect", "cancel"])
async def test_context_closed_for_every_stream_termination(monkeypatch, termination):
    lifecycle = []

    @asynccontextmanager
    async def factory(agent, ctx):
        lifecycle.append(("open", ctx.invocation_id))
        try:
            yield CodexProviderEndpoint("http://127.0.0.1:1234/v1", "fixture-key")
        finally:
            lifecycle.append(("close", ctx.invocation_id))

    async def execution(self, agent, ctx, *, provider_endpoint=None):
        assert provider_endpoint.api_key == "fixture-key"
        yield "event"
        if termination == "error":
            raise RuntimeError("test execution failure")
        if termination == "cancel":
            await asyncio.Event().wait()

    monkeypatch.setattr(CodexRuntime, "_run_async", execution)
    stream = CodexRuntime().run_async(
        agent(factory), SimpleNamespace(invocation_id="run")
    )
    async with aclosing(stream):
        assert await anext(stream) == "event"
        if termination == "complete":
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
        elif termination == "error":
            with pytest.raises(RuntimeError, match="test execution failure"):
                await anext(stream)
        elif termination == "cancel":
            task = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert lifecycle == [("open", "run"), ("close", "run")]


@pytest.mark.asyncio
async def test_absent_extension_uses_original_path(monkeypatch):
    async def execution(self, agent, ctx, *, provider_endpoint=None):
        assert provider_endpoint is None
        yield "original-event"

    monkeypatch.setattr(CodexRuntime, "_run_async", execution)
    assert [event async for event in CodexRuntime().run_async(agent(), object())] == [
        "original-event"
    ]


@pytest.mark.asyncio
async def test_invalid_provider_never_falls_back_and_always_closes(monkeypatch):
    closed = []

    @asynccontextmanager
    async def factory(agent, ctx):
        try:
            yield "invalid-provider"
        finally:
            closed.append(True)

    async def execution(*args, **kwargs):
        pytest.fail("invalid factory must not fall back")
        yield

    monkeypatch.setattr(CodexRuntime, "_run_async", execution)
    with pytest.raises(TypeError, match="CodexProviderEndpoint"):
        await anext(CodexRuntime().run_async(agent(factory), object()))
    assert closed == [True]


@pytest.mark.asyncio
async def test_concurrent_invocations_do_not_replace_agent_credentials(monkeypatch):
    @asynccontextmanager
    async def factory(agent, ctx):
        yield CodexProviderEndpoint("http://127.0.0.1:1234/v1", ctx.invocation_id)

    async def execution(self, agent, ctx, *, provider_endpoint=None):
        await asyncio.sleep(0)
        yield provider_endpoint.api_key

    monkeypatch.setattr(CodexRuntime, "_run_async", execution)
    shared = agent(factory)
    shared.model_api_key = "original"

    async def run(name):
        return [
            e
            async for e in CodexRuntime().run_async(
                shared, SimpleNamespace(invocation_id=name)
            )
        ]

    assert await asyncio.gather(run("one"), run("two")) == [["one"], ["two"]]
    assert shared.model_api_key == "original"


def test_endpoint_credential_is_not_in_repr():
    assert "fixture-secret" not in repr(
        CodexProviderEndpoint("http://127.0.0.1:1234/v1", "fixture-secret")
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.invalid",
        "https://example.invalid?key=secret",
    ],
)
def test_provider_endpoint_rejects_embedded_credentials(url):
    with pytest.raises(ValueError):
        CodexProviderEndpoint(url, "fixture")


def test_factory_survives_environment_resolution_without_deepcopy(monkeypatch):
    class Factory:
        def __deepcopy__(self, memo):
            raise AssertionError("A provider context cannot be deep copied")

        def __call__(self, agent, ctx):
            return None

    factory = Factory()
    configured = agent(factory)
    monkeypatch.setenv("VEADK_CODEX_THREAD_MODE", "ephemeral")
    resolved = CodexRuntimeConfig.from_agent(configured)
    assert resolved.provider_factory is factory
    assert resolved.thread_mode == "ephemeral"
    assert configured.codex_runtime_config.thread_mode == "resume"


def test_factory_is_absent_from_editable_json_schema():
    assert (
        "provider_factory" not in CodexRuntimeConfig.model_json_schema()["properties"]
    )


@pytest.mark.asyncio
async def test_endpoint_decorates_only_existing_executors():
    from veadk.runtime.codex.provider_extension import wrap_provider_executors

    seen = []

    async def execute(args, call_id):
        seen.append((args, call_id))
        return "result"

    def wrap(name, executor):
        async def decorated(args, call_id):
            assert name == "read"
            return await executor(args, call_id)

        return decorated

    endpoint = CodexProviderEndpoint(
        "http://127.0.0.1:1234/v1", "fixture", wrap_tool_executor=wrap
    )
    original = {"read": execute}
    decorated = wrap_provider_executors(endpoint, original)
    assert set(decorated) == set(original)
    assert await decorated["read"]({"value": 1}, "call") == "result"
    assert seen == [({"value": 1}, "call")]
    assert original["read"] is execute
    assert wrap_provider_executors(None, original) is original


def test_invalid_executor_decorator_fails_before_registration():
    from veadk.runtime.codex.provider_extension import wrap_provider_executors

    endpoint = CodexProviderEndpoint(
        "http://127.0.0.1:1234/v1", "fixture", wrap_tool_executor=lambda *args: None
    )
    with pytest.raises(TypeError, match="executor"):
        wrap_provider_executors(endpoint, {"read": lambda *args: None})


def test_native_policy_options_preserve_defaults_and_validate():
    default = CodexRuntimeConfig()
    assert default.compact_prompt is None
    assert default.tool_output_token_limit is None
    assert default.shell_enabled is True
    with pytest.raises(ValidationError):
        CodexRuntimeConfig(tool_output_token_limit=0)
