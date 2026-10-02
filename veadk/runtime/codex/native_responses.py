"""Request-scoped native Responses streams for OpenAI-compatible endpoints.

LiteLLM 1.83 treats unregistered model names as non-streaming and silently
buffers them. Use the protocol SDK for streaming instead of changing LiteLLM's
global model registry, prices or capabilities for unrelated tenants.
"""

from __future__ import annotations

import inspect

from openai import AsyncOpenAI
from openai.resources.responses import AsyncResponses

_CREATE_PARAMETERS = frozenset(inspect.signature(AsyncResponses.create).parameters)


def _preserve_wire_fields(request):
    """Carry newer wire fields through the installed SDK's JSON extension slot."""
    extensions = dict(request.get("extra_body") or {})
    for name in tuple(request):
        if name in _CREATE_PARAMETERS:
            continue
        value = request.pop(name)
        if name in extensions and extensions[name] != value:
            # Include neither field values nor request payload in the exception.
            raise ValueError("Conflicting Responses field")
        extensions[name] = value
    if extensions:
        request["extra_body"] = extensions
    return request


class _OwnedStream:
    def __init__(self, stream, client):
        self.stream = stream
        self.client = client

    def __aiter__(self):
        return self.stream.__aiter__()

    async def aclose(self):
        try:
            await self.stream.close()
        finally:
            await self.client.close()


async def request_native_stream(**kwargs):
    request = dict(kwargs)
    client_options = {
        "base_url": request.pop("api_base"),
        "api_key": request.pop("api_key"),
        "max_retries": request.pop("num_retries", 0),
    }
    if "timeout" in request:
        client_options["timeout"] = request.pop("timeout")
    request.pop("custom_llm_provider", None)
    request.pop("drop_params", None)
    request["model"] = request["model"].removeprefix("openai/")
    request = _preserve_wire_fields(request)
    client = AsyncOpenAI(**client_options)
    try:
        stream = await client.responses.create(**request)
        return _OwnedStream(stream, client)
    except BaseException:
        await client.close()
        raise
