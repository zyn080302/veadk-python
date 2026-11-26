"""Regress the actual Runtime -> SDK turn submission boundary."""

from __future__ import annotations


import pytest
from google.adk.events.event import Event
from google.adk.sessions.session import Session
from google.genai import types

from test_codex_runtime_sdk import (
    _Agent,
    _Context,
    _FakeAsyncCodex,
    _FakeShim,
    _FakeTurn,
)
from veadk.runtime.codex.config import CodexRuntimeConfig
from veadk.runtime.codex.runtime import CodexRuntime


@pytest.mark.asyncio
async def test_overflow_runtime_preserves_current_and_registers_readable_source(
    monkeypatch,
):
    from veadk.runtime.codex import runtime as runtime_module

    calls = {}
    shim = _FakeShim()

    async def get_shim(*args):
        return shim

    class Thread:
        async def turn(self, items, **kwargs):
            text = "".join(item.text for item in items if hasattr(item, "text"))
            calls["text"] = text
            if len(text) > 1048576:
                raise ValueError(
                    "Input exceeds the maximum length of 1048576 characters."
                )
            return _FakeTurn()

    class Client(_FakeAsyncCodex):
        async def thread_start(self, **kwargs):
            return Thread()

    monkeypatch.setattr(runtime_module, "get_shim", get_shim)
    monkeypatch.setattr(runtime_module, "AsyncCodex", Client)
    monkeypatch.setattr(
        runtime_module, "sync_skills_to_codex_home", lambda *a, **k: None
    )
    agent = _Agent()
    agent.codex_runtime_config = CodexRuntimeConfig(shell_enabled=False)
    current = "What is the supported approval mode? Cite evidence ticket SYNTH-73."
    evidence = (
        "old filler " * 65000
        + " SYNTH-73: supervised approval is supported. "
        + "old filler " * 65000
    )
    content = types.Content(role="user", parts=[types.Part(text=current)])
    ctx = _Context(
        invocation_id="length-test",
        agent=agent,
        branch=None,
        isolation_scope=None,
        user_content=content,
        session=Session(
            id="length-test",
            appName="test",
            userId="test",
            state={},
            events=[
                Event(
                    author="agent",
                    content=types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name="knowledge_search", response={"text": evidence}
                                )
                            )
                        ],
                    ),
                )
            ],
        ),
    )
    events = [e async for e in CodexRuntime().run_async(agent, ctx)]
    assert not any(e.error_code for e in events)
    assert len(calls["text"]) <= 1048576
    assert current in calls["text"]
    assert "<veadk_turn>turn-marker</veadk_turn>" in calls["text"]
    specs = shim.registered[0]["specs"]
    assert any(s["name"] == "_veadk_read_context" for s in specs)
    assert "supervised approval is supported" not in calls["text"]
    assert shim.unregistered == ["opaque-turn-token"]


def _archive():
    from veadk.runtime.codex.input_context import InputContext

    store = InputContext()
    source = "old evidence " * 100000 + " final evidence"
    packed = store.pack(source, current="What does the final evidence say?")
    import re

    reference = re.search(r"context_[0-9a-f]{24}", packed).group()
    return store, source, reference, packed


@pytest.mark.parametrize(
    "size,reserve", [(0, 0), (1048576, 0), (1048512, 64), (400000, 0)]
)
def test_ordinary_input_exact(size, reserve):
    from veadk.runtime.codex.input_context import InputContext

    source = "知" * size
    store = InputContext()
    assert store.pack(source, current=source, reserve=reserve) == source
    assert store.notice() == ""


def test_source_reconstructs_without_loss_and_unicode_uses_characters():
    store, source, reference, packed = _archive()
    assert len(packed) < 262144
    chunks = []
    offset = 0
    while offset is not None:
        page = store.read(reference, offset)
        assert len(page["text"]) <= 16000
        chunks.append(page["text"])
        offset = page["next_offset"]
    assert "".join(chunks) == source
    assert store.read(reference, len(source))["next_offset"] is None


def test_middle_fact_search_is_exact_and_not_found_distinct_from_unavailable():
    store, source, reference, _ = _archive()
    page = store.read(reference, query="final evidence")
    assert page["text"] == "final evidence"
    assert page["offset"] == source.index("final evidence")
    assert page["matched"] is True
    missing = store.read(reference, query="does not occur")
    assert missing["matched"] is False and missing["status"] == "ok"
    assert store.read("unknown")["status"] == "error"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"offset": -1},
        {"offset": True},
        {"offset": 1.5},
        {"offset": 2000000},
        {"length": 0},
        {"length": 16001},
        {"length": True},
        {"length": "10"},
        {"query": None},
        {"query": "x" * 257},
        {"reference": None},
    ],
)
def test_invalid_reader_arguments_are_bounded_errors(kwargs):
    store, _, reference, _ = _archive()
    args = {"reference": reference, **kwargs}
    assert store.read(**args)["status"] == "error"


def test_input_context_isolation_and_cleanup():
    from veadk.runtime.codex.input_context import InputContext

    store, _, reference, _ = _archive()
    other = InputContext()
    assert other.read(reference)["status"] == "error"
    assert store.read(reference)["status"] == "ok"
    store.clear()
    assert store.read(reference)["status"] == "error"


def test_current_request_overflow_retains_full_text_and_marker_space():
    from veadk.runtime.codex.input_context import InputContext
    import re

    source = "知" * 524289 + "EXACT-MIDDLE-FACT" + "文" * 524289
    store = InputContext()
    packed = store.pack(source, current=source, reserve=64)
    assert len(packed) + 64 < 262144
    reference = re.search(r"context_[0-9a-f]{24}", packed).group()
    page = store.read(reference, query="EXACT-MIDDLE-FACT", length=17)
    assert page["text"].startswith("EXACT-MIDDLE-FACT")


def test_reserved_marker_can_trigger_packing_at_exact_rpc_limit():
    from veadk.runtime.codex.input_context import InputContext

    store = InputContext()
    source = "x" * 1048576
    packed = store.pack(source, current="current", reserve=64)
    assert packed != source and len(packed) + 64 <= 1048576


def test_internal_read_is_not_recursive_history_or_hidden_reasoning():
    from veadk.runtime.codex.translate import build_prompt_from_llm_request
    from veadk.runtime.model_callbacks import _build_request_contents
    from google.adk.models.llm_request import LlmRequest

    agent = _Agent()
    parts = [
        types.Part(text="private reasoning sentinel", thought=True),
        types.Part(
            function_response=types.FunctionResponse(
                name="_veadk_read_context", response={"text": "recursive sentinel"}
            )
        ),
        types.Part(text="authorized evidence"),
    ]
    ctx = _Context(
        user_content=types.Content(role="user", parts=[types.Part(text="current")]),
        session=Session(
            id="s",
            appName="a",
            userId="u",
            events=[
                Event(author="agent", content=types.Content(role="model", parts=parts))
            ],
        ),
    )
    request = LlmRequest(contents=_build_request_contents(agent, ctx))
    prompt = build_prompt_from_llm_request(request)
    assert "recursive sentinel" not in prompt
    assert "private reasoning sentinel" not in prompt
    assert "authorized evidence" in prompt and "current" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "cancel", "timeout"])
async def test_registered_context_cleared_on_actual_runtime_exit(monkeypatch, outcome):
    import asyncio
    import sys
    from veadk.runtime.codex import runtime as runtime_module
    from veadk.runtime.codex.input_context import InputContext

    instances = []

    class ObservedContext(InputContext):
        def __init__(self):
            super().__init__()
            instances.append(self)

    class ExitTurn(_FakeTurn):
        def stream(self):
            assert instances[-1]._sources
            if outcome == "cancel":
                raise asyncio.CancelledError()
            if outcome == "timeout":
                raise TimeoutError("synthetic transport timeout")
            return super().stream()

    monkeypatch.setattr(runtime_module, "InputContext", ObservedContext)
    monkeypatch.setattr(sys.modules[__name__], "_FakeTurn", ExitTurn)
    run = test_overflow_runtime_preserves_current_and_registers_readable_source(
        monkeypatch
    )
    if outcome == "complete":
        await run
    else:
        error = asyncio.CancelledError if outcome == "cancel" else TimeoutError
        with pytest.raises(error):
            await run
    assert len(instances) == 1
    assert instances[0]._sources == {}
    assert instances[0].notice() == ""
