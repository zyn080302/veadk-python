"""Native input media through real Runner; all bytes and endpoints are fixtures."""

import base64
import copy
import importlib
import json
from contextlib import aclosing
from dataclasses import replace

import httpx
import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import SecretStr

from veadk import Agent
from veadk.runtime import get_runtime
from veadk.runtime.customer import CustomerChannelError
from tests.runtime.customer.test_native_channel import (
    CONFIG,
    NativeHost,
    collect,
    request,
)
from tests.runtime.customer.test_runtime import IDENTITY, setup as runtime_setup, turn

setup = runtime_setup


def media(mime="image/png", data=b"\x89PNG\r\n\x1a\nfixture"):
    return {
        "inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()},
        "part_metadata": {"file": {"name": "fixture", "size": len(data)}},
    }


async def send(agent, sessions, message):
    runner = Runner(agent=agent, app_name="app", session_service=sessions)
    async with aclosing(
        runner.run_async(
            user_id="user-a",
            session_id="session-a",
            new_message=types.Content.model_validate(message),
        )
    ) as stream:
        return [event async for event in stream]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "part",
    [
        media(data=b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024)),
        media("application/pdf", b"%PDF-fixture"),
        media("image/jpeg", b"\xff\xd8fixture\xff\xd9"),
        media("image/webp", b"RIFF0000WEBPfixture"),
        {
            "text": "<user_attachment>fixture data</user_attachment>",
            "part_metadata": {
                "display": {"hideText": True},
                "file": {"name": "data.csv"},
            },
        },
    ],
)
async def test_runner_preserves_native_attachments_and_sends_only_new_followup(
    setup, part
):
    config, _, sessions = setup
    host = NativeHost(batches=())
    config = replace(
        config,
        protocol="native",
        agent_config=CONFIG,
        transport=httpx.MockTransport(host.handle),
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    message = {"role": "user", "parts": [part]}
    original = copy.deepcopy(message)
    output = await send(agent, sessions, message)
    assert output[-1].turn_complete
    assert message == original
    sent = json.loads(host.requests[-1].content)["newMessage"]
    assert types.Content.model_validate(sent) == types.Content.model_validate(original)
    saved = await sessions.get_session(**IDENTITY)
    assert [e.content for e in saved.events if e.author == "user"] == [
        types.Content.model_validate(original)
    ]
    await turn(agent, sessions, text="follow-up")
    assert json.loads(host.requests[-1].content)["newMessage"] == {
        "role": "user",
        "parts": [{"text": "follow-up"}],
    }
    saved = await sessions.get_session(**IDENTITY)
    users = [e.content for e in saved.events if e.author == "user"]
    assert len(users) == 2 and users[0] == types.Content.model_validate(original)
    assert all(s.closed for s in host.streams)


@pytest.mark.parametrize(
    "parts",
    [
        [{"fileData": {"fileUri": "https://fixture.invalid/image.png"}}],
        [{"functionCall": {"name": "lookup", "args": {}}}],
        [{"functionResponse": {"name": "lookup", "response": {}}}],
        [{"text": "query", "thought": True}],
        [{"text": "query", "inline_data": media()["inline_data"]}],
        [{"text": "query", "part_metadata": [], "partMetadata": {}}],
        [{"text": "query", "part_metadata": {"items": list(range(256))}}],
        [{"text": "query", "part_metadata": {"data": "x" * (16 * 1024)}}],
        [{"text": "query", "part_metadata": {"data": float("nan")}}],
        [
            {
                "text": "query",
                "part_metadata": {
                    "data": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": 1}}}}}}}}
                },
            }
        ],
        [{"text": "x" * (1024 * 1024 + 1)}],
        [{"text": " "}],
        [media()] * 4,
        [{"text": "x"}] * 9,
        [media(data=b"\x89PNG\r\n\x1a\n" + b"x" * (4 * 1024 * 1024))],
        [media(data=b"\x89PNG\r\n\x1a\n" + b"x" * (3 * 1024 * 1024))] * 2,
        [media("text/plain", b"fixture")],
        [media("application/pdf", b"wrong header")],
        [{"inlineData": {"mimeType": "image/png", "data": "not base64"}}],
        [{"inlineData": {"mimeType": "image/png", "data": ""}}],
        [
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "mime_type": "image/png",
                    "data": "AA==",
                }
            }
        ],
    ],
)
def test_invalid_native_inputs_rejected_with_no_payload_in_error(parts):
    from veadk.runtime.customer.messages import validate_user_message

    with pytest.raises(CustomerChannelError) as error:
        validate_user_message({"role": "user", "parts": parts}, attachments=True)
    assert str(error.value) == "unsupported_user_message"


def test_aliases_metadata_and_genai_base64_are_preserved_without_sharing_mutable_state():
    from veadk.runtime.customer.messages import validate_user_message

    part = media("image/jpeg", b"\xff\xd8fixture\xff\xd9")
    blob = part["inline_data"]
    blob["data"] = base64.urlsafe_b64encode(b"\xff\xd8fixture\xff\xd9").decode()
    message = {
        "role": "user",
        "parts": [
            {
                "inlineData": {
                    "mimeType": blob["mime_type"],
                    "data": blob["data"],
                    "displayName": "fixture.jpg",
                },
                "partMetadata": part["part_metadata"],
            }
        ],
    }
    normalized = validate_user_message(message, attachments=True)
    assert types.Content.model_validate(normalized) == types.Content.model_validate(
        message
    )
    message["parts"][0]["partMetadata"]["file"]["name"] = "changed"
    assert normalized["parts"][0]["part_metadata"]["file"]["name"] == "fixture"


@pytest.mark.asyncio
async def test_shared_runtime_still_rejects_attachment_before_http(setup):
    config, host, sessions = setup
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(CustomerChannelError, match="unsupported_user_message"):
        await send(agent, sessions, {"role": "user", "parts": [media()]})
    assert host.requests == []


@pytest.mark.asyncio
async def test_native_rejects_large_configuration_before_session_http(setup):
    config, _, sessions = setup
    host = NativeHost(batches=())
    config = replace(
        config,
        protocol="native",
        agent_config=SecretStr(json.dumps({"instructions": "x" * (8 * 1024 * 1024)})),
        transport=httpx.MockTransport(host.handle),
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    with pytest.raises(CustomerChannelError, match="request_too_large"):
        await send(agent, sessions, {"role": "user", "parts": [media()]})
    assert host.requests == []


@pytest.mark.asyncio
async def test_native_initial_budget_is_opt_in_for_channel_callers():
    host = NativeHost(batches=())
    message = {
        "role": "user",
        "parts": [media(data=b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024))],
    }
    run = request().model_copy(update={"new_message": message})
    with pytest.raises(CustomerChannelError, match="request_too_large"):
        await collect(host, run)
    assert host.requests == []
    result = await collect(host, run, max_initial_request_bytes=8 * 1024 * 1024)
    assert result[-1]["type"] == "run.completed"
    assert len(host.requests) == 1


@pytest.mark.asyncio
async def test_larger_initial_budget_does_not_expand_tool_results():
    host = NativeHost(batches=(1,))

    async def large_result(args, request_id):
        return {"data": "x" * (2 * 1024 * 1024)}

    host.execute = large_result
    with pytest.raises(CustomerChannelError, match="request_too_large"):
        await collect(host, max_initial_request_bytes=8 * 1024 * 1024)
    assert len(host.requests) == 1 and host.results == []
    assert all(stream.closed for stream in host.streams)


@pytest.mark.asyncio
async def test_larger_initial_budget_does_not_expand_output_events():
    host = NativeHost(batches=())
    host.mutation = lambda output: output[0]["content"]["parts"].append(
        {"text": "x" * (1024 * 1024)}
    )
    with pytest.raises(CustomerChannelError, match="event_too_large"):
        await collect(host, request(), max_initial_request_bytes=8 * 1024 * 1024)
    assert len(host.requests) == 1
    assert all(stream.closed for stream in host.streams)


@pytest.mark.asyncio
async def test_display_recovery_preserves_original_attachment_without_replaying_host(
    setup,
):
    config, _, _ = setup
    host = NativeHost(batches=())
    config = replace(
        config,
        protocol="native",
        agent_config=CONFIG,
        transport=httpx.MockTransport(host.handle),
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )

    class Sessions(InMemorySessionService):
        fail = True

        async def append_event(self, session, event):
            if self.fail and event.author != "user" and event.turn_complete:
                raise RuntimeError("synthetic display failure")
            return await super().append_event(session, event)

    sessions = Sessions()
    await sessions.create_session(**IDENTITY)
    message = {"role": "user", "parts": [media("application/pdf", b"%PDF-fixture")]}
    with pytest.raises(RuntimeError, match="synthetic display failure"):
        await send(agent, sessions, message)
    requests_before = len(host.requests)
    sessions.fail = False
    await config.store._engine.dispose()
    assert (
        await get_runtime("customer").recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
        == 1
    )
    assert (
        await get_runtime("customer").recover_display(
            agent, sessions, tuple(IDENTITY.values())
        )
        == 0
    )
    assert len(host.requests) == requests_before
    saved = await sessions.get_session(**IDENTITY)
    assert [e.content for e in saved.events if e.author == "user"] == [
        types.Content.model_validate(message)
    ]
    await turn(agent, sessions, text="next")
    assert json.loads(host.requests[-1].content)["newMessage"] == {
        "role": "user",
        "parts": [{"text": "next"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/run", "/run_sse"])
async def test_standard_harness_accepts_native_media_and_serves_original_history(
    setup, monkeypatch, route
):
    from veadk.memory.short_term_memory import ShortTermMemory

    config, _, sessions = setup
    host = NativeHost(batches=())
    config = replace(
        config,
        protocol="native",
        agent_config=CONFIG,
        transport=httpx.MockTransport(host.handle),
    )
    agent = Agent(
        name="customer_agent", runtime="customer", customer_runtime_config=config
    )
    module = importlib.import_module("veadk.cloud.harness_app.app")
    monkeypatch.setattr(module, "build_harness_plugins_from_runtime_env", lambda: [])
    app = module.HarnessApp(agent, ShortTermMemory(session_service=sessions), "app").app
    first = {"role": "user", "parts": [media("image/jpeg", b"\xff\xd8fixture\xff\xd9")]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        for message in [first, {"role": "user", "parts": [{"text": "follow-up"}]}]:
            result = await client.post(
                route, json={**IDENTITY, "new_message": message, "streaming": True}
            )
            assert result.status_code == 200 and "answer" in result.text
            assert "error" not in result.text.lower()
        saved = (await client.get("/apps/app/users/user-a/sessions/session-a")).json()
    users = [
        types.Content.model_validate(e["content"])
        for e in saved["events"]
        if e["author"] == "user"
    ]
    assert len(users) == 2 and users[0] == types.Content.model_validate(first)
    assert json.loads(host.requests[-1].content)["newMessage"] == {
        "role": "user",
        "parts": [{"text": "follow-up"}],
    }
