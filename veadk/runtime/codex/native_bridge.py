"""Invocation-scoped MCP tools and transparent Responses transport.

Codex owns tool dispatch and history. This service never invokes a tool from
a model response and never inserts tool declarations or results into input.
Only the MCP route can invoke an ADK executor.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
import uuid

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


class NativeBridge:
    # Optional application transport adapter. It may project provider output,
    # but tool execution always remains on the MCP endpoint.
    response_backend = None

    def __init__(
        self, api_base: str, api_key: str, *, transport=None, tool_format="native"
    ):
        self.api_base = api_base.rstrip("/")
        self._api_key = api_key
        self.url = ""
        self._token = ""
        self._specs = []
        self._executors = {}
        self._budget = 32
        self._count = 0
        self._tasks: set[asyncio.Task] = set()
        self._server = None
        self._server_task = None
        self._error = None
        self._halted = False
        self._closed = False
        self._on_model_call = None
        self._extra = {}
        self._headers = {}
        self._tool_format = tool_format
        from veadk.runtime.codex.native_transport import SummaryCompatibility

        self._summary_compatibility = SummaryCompatibility()
        self._client = httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(600, connect=15), trust_env=False
        )
        self.mcp = Server("veadk")

        @self.mcp.list_tools()
        async def list_tools():
            return [
                types.Tool(
                    name=s["name"],
                    description=s.get("description", ""),
                    inputSchema=s.get("parameters", {"type": "object"}),
                    annotations=s.get("annotations"),
                )
                for s in self._specs
            ]

        @self.mcp.call_tool()
        async def call_tool(name, arguments):
            meta = self.mcp.request_context.meta
            call_id = getattr(meta, "callId", None)
            if not isinstance(call_id, str) or not call_id or len(call_id) > 512:
                call_id = None
            return await self.execute(name, arguments or {}, call_id=call_id)

        self.app = self._build_app()

    def _build_app(self):
        manager = StreamableHTTPSessionManager(
            app=self.mcp, json_response=True, stateless=True
        )

        @contextlib.asynccontextmanager
        async def lifespan(app):
            async with manager.run():
                yield

        app = FastAPI(lifespan=lifespan)

        # Authenticate both endpoints before MCP reads any request body.
        @app.middleware("http")
        async def authenticate(request, call_next):
            value = request.headers.get("authorization", "")
            if (
                self._closed
                or not self._token
                or not secrets.compare_digest(value, "Bearer " + self._token)
            ):
                return Response(status_code=401)
            return await call_next(request)

        @app.post("/v1/responses")
        async def responses(request: Request):
            body = await request.json()
            if not isinstance(body, dict) or not body.get("model"):
                return Response(status_code=400)
            if self._halted:
                # A pending ADK confirmation/auth/transfer ends the invocation;
                # it must not trigger another model call or another side effect.
                from veadk.runtime.codex.proxy import _synth_sse

                result = {
                    "id": "resp_" + uuid.uuid4().hex,
                    "object": "response",
                    "created_at": int(time.time()),
                    "status": "completed",
                    "model": body["model"],
                    "output": [],
                }
                if body.get("stream"):
                    return StreamingResponse(
                        _synth_sse(result), media_type="text/event-stream"
                    )
                return JSONResponse(result)
            try:
                if self._on_model_call:
                    self._on_model_call()
            except Exception as error:
                self._error = error
                return JSONResponse(
                    {
                        "error": {
                            "message": "Model call budget exhausted",
                            "type": "budget_exhausted",
                        }
                    },
                    status_code=409,
                )
            # Runtime-level generation settings may be added but must never
            # overwrite Codex's input, tools, model, or protocol controls.
            body = {**self._extra, **body}
            adapter = None
            if self._tool_format == "functions":
                from veadk.runtime.codex.tool_wire import ToolWireAdapter

                adapter = ToolWireAdapter()
                try:
                    body = adapter.request(body)
                except ValueError as error:
                    self._error = error
                    return JSONResponse(
                        {
                            "error": {
                                "message": str(error),
                                "type": "unsupported_tool_schema",
                            }
                        },
                        status_code=400,
                    )
            if self.response_backend is not None:
                try:
                    # The hook receives protocol data and local credentials
                    # for the authorized provider only; never a tool executor.
                    known = {
                        "temperature",
                        "top_p",
                        "max_output_tokens",
                        "reasoning",
                        "text",
                    }
                    extras = {k: v for k, v in self._extra.items() if k not in known}
                    result = await self._summary_compatibility.call(
                        self.response_backend,
                        **{k: v for k, v in body.items() if k not in extras},
                        api_base=self.api_base,
                        api_key=self._api_key,
                        extra_headers=self._headers,
                        extra_body=extras,
                        veadk_tool_names=adapter.business_names(
                            body.get("tools", []), self._executors
                        )
                        if adapter
                        else {},
                    )
                except Exception as error:
                    status = getattr(error, "status_code", 502)
                    status = (
                        status
                        if isinstance(status, int) and 400 <= status <= 599
                        else 502
                    )
                    return JSONResponse(
                        {
                            "error": {
                                "message": "Responses backend rejected the request",
                                "type": "backend_error",
                            }
                        },
                        status_code=status,
                    )
                from veadk.runtime.codex.native_transport import encode_backend_result

                if not body.get("stream") and isinstance(result, dict):
                    if adapter:
                        result = adapter.event(
                            {"type": "response.completed", "response": result}
                        )[0]["response"]
                    return JSONResponse(result)
                return StreamingResponse(
                    encode_backend_result(result, adapter),
                    media_type="text/event-stream",
                )

            async def send(**payload):
                from veadk.runtime.codex.native_transport import (
                    SummaryPreferenceRejected,
                    rejects_summary,
                )

                outgoing = self._client.build_request(
                    "POST",
                    self.api_base + "/responses",
                    json=payload,
                    headers={
                        **self._headers,
                        "Authorization": "Bearer " + self._api_key,
                    },
                )
                result = await self._client.send(outgoing, stream=True)
                reasoning = payload.get("reasoning")
                if (
                    result.status_code == 400
                    and isinstance(reasoning, dict)
                    and "summary" in reasoning
                ):
                    try:
                        await result.aread()
                        if rejects_summary(result.status_code, result.text):
                            raise SummaryPreferenceRejected()
                    finally:
                        await result.aclose()
                return result

            try:
                response = await self._summary_compatibility.call(send, **body)
            except httpx.HTTPError:
                return JSONResponse(
                    {
                        "error": {
                            "message": "Responses transport failed",
                            "type": "transport_error",
                        }
                    },
                    status_code=502,
                )

            async def chunks():
                try:
                    if adapter is None:
                        async for chunk in response.aiter_raw():
                            yield chunk
                    elif body.get("stream"):
                        from veadk.runtime.codex.tool_wire import adapt_sse

                        async for chunk in adapt_sse(response.aiter_lines(), adapter):
                            yield chunk
                    else:
                        raw = await response.aread()
                        event = adapter.event(
                            {"type": "response.completed", "response": json.loads(raw)}
                        )[0]
                        yield json.dumps(event["response"]).encode()
                except ValueError as error:
                    self._error = error
                    # A malformed tool input must be terminal; never disguise
                    # it as an empty completed response.
                    yield (
                        "event: response.failed\ndata: "
                        + json.dumps(
                            {
                                "type": "response.failed",
                                "response": {
                                    "status": "failed",
                                    "output": [],
                                    "error": {
                                        "code": "invalid_prompt",
                                        "message": "Native tool protocol decoding failed",
                                    },
                                },
                            }
                        )
                        + "\n\n"
                    ).encode()
                finally:
                    await response.aclose()

            if response.is_error:
                # Provider errors can echo submitted content or credentials.
                # Preserve status for retry policy, keep diagnostics local.
                await response.aclose()
                return JSONResponse(
                    {
                        "error": {
                            "message": "Responses backend rejected the request",
                            "type": "backend_error",
                        }
                    },
                    status_code=response.status_code,
                )
            return StreamingResponse(
                chunks(),
                status_code=response.status_code,
                media_type=response.headers.get("content-type", "application/json"),
                headers={"content-encoding": response.headers["content-encoding"]}
                if adapter is None and "content-encoding" in response.headers
                else None,
            )

        # Mount at / rather than /mcp/ to avoid an authentication-bearing
        # redirect when Codex uses the standard /mcp endpoint.
        class MCPRoute:
            async def __call__(self, scope, receive, send):
                if scope.get("path") != "/mcp":
                    await Response(status_code=404)(scope, receive, send)
                    return
                await manager.handle_request(scope, receive, send)

        app.mount("/", MCPRoute())
        return app

    @property
    def active_calls(self):
        return len(self._tasks)

    def register_turn(
        self,
        specs,
        executors,
        *,
        max_tool_iterations=32,
        invocation_id="",
        model_extra_config=None,
        on_model_call=None,
    ):
        if self._token:
            raise RuntimeError("Native bridge already has an invocation")
        extra = dict(model_extra_config or {})
        headers = extra.pop("extra_headers", {})
        if not isinstance(headers, dict):
            raise ValueError("extra_headers must be an object")
        self._headers = {
            str(k): str(v)
            for k, v in headers.items()
            if v is not None
            and k.lower() not in {"authorization", "host", "content-length", "cookie"}
        }
        body = extra.pop("extra_body", {})
        if not isinstance(body, dict):
            raise ValueError("extra_body must be an object")
        # These are Agent defaults for chat prompt caching, which is rejected
        # by Responses when Codex supplies its native instructions.
        body = {k: v for k, v in body.items() if k not in {"caching", "expire_at"}}
        protected = {
            "input",
            "instructions",
            "tools",
            "model",
            "stream",
            "previous_response_id",
            "store",
        }
        if body.keys() & protected:
            raise ValueError("extra_body cannot override Codex protocol fields")
        allowed = {"temperature", "top_p", "max_output_tokens", "reasoning", "text"}
        if extra.keys() - allowed:
            raise ValueError(
                "Unsupported native Responses model_extra_config keys: "
                + ", ".join(sorted(extra.keys() - allowed))
            )
        self._extra = {**body, **extra}
        self._specs, self._executors = list(specs), dict(executors)
        self._budget = max_tool_iterations
        self._on_model_call = on_model_call
        self._token = secrets.token_urlsafe(32)
        return self._token

    def unregister_turn(self, token):
        self._token = ""

    def turn_marker(self, token):
        return ""

    def turn_error(self, token):
        return self._error

    async def execute(self, name, arguments, *, call_id=None):
        task = asyncio.current_task()
        if self._closed or self._halted or name not in self._executors:
            return self._tool_error("Tool unavailable for this invocation")
        if self._count >= self._budget:
            self._error = RuntimeError("Codex tool iteration budget exhausted")
            self._halted = True
            return self._tool_error("Tool call budget exhausted")
        self._count += 1
        self._tasks.add(task)
        try:
            # Codex supplies the model's callId as MCP request metadata. MCP
            # transport request IDs are unrelated and must never be used here.
            result = await self._executors[name](
                arguments, call_id or "mcp_adk_" + uuid.uuid4().hex
            )
            try:
                status = json.loads(result).get("status")
            except (ValueError, AttributeError):
                status = None
            if status in {
                "pending",
                "authentication_required",
                "confirmation_required",
                "transferred",
            }:
                self._halted = True
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=result)],
                isError=status == "failed",
            )
        finally:
            self._tasks.discard(task)

    @staticmethod
    def _tool_error(message):
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)], isError=True
        )

    async def start(self):
        config = uvicorn.Config(
            self.app, host="127.0.0.1", port=0, log_level="critical", access_log=False
        )
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None
        self._server_task = asyncio.create_task(self._server.serve())
        try:

            async def wait_started():
                while not self._server.started:
                    if self._server_task.done():
                        await self._server_task
                        raise RuntimeError("Native bridge exited before startup")
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_started(), 10)
            port = self._server.servers[0].sockets[0].getsockname()[1]
            self.url = f"http://127.0.0.1:{port}"
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._server:
            self._server.should_exit = True
        if self._server_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._server_task), 10)
            except asyncio.TimeoutError:
                self._server_task.cancel()
                await asyncio.gather(self._server_task, return_exceptions=True)
        await self._client.aclose()
