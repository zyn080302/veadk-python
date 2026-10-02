"""Deterministic loopback Responses service; all payloads are synthetic."""

import asyncio
import contextlib
import json
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


class NativeHTTPBackend:
    def __init__(self):
        self.requests = []
        self.app = FastAPI()

        @self.app.post("/v1/responses")
        async def responses(request: Request):
            body = await request.json()
            self.requests.append(body)
            result = self._script(body)
            return StreamingResponse(
                self._events(result), media_type="text/event-stream"
            )

    async def _events(self, result):
        from veadk.runtime.codex.proxy import _synth_sse

        async for chunk in _synth_sse(result):
            yield chunk

    async def start(self):
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=0,
                log_level="critical",
                access_log=False,
                lifespan="off",
            )
        )
        self.task = asyncio.create_task(self.server.serve())
        while not self.server.started:
            if self.task.done():
                await self.task
            await asyncio.sleep(0.01)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def stop(self):
        self.server.should_exit = True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.task, 5)

    @staticmethod
    def _function_call(name, arguments, *, call_id):
        return {
            "type": "function_call",
            "id": "fc_" + uuid.uuid4().hex,
            "call_id": call_id,
            "name": name,
            "arguments": json.dumps(arguments),
            "status": "completed",
        }

    @staticmethod
    def _message(text):
        return {
            "type": "message",
            "id": "msg_" + uuid.uuid4().hex,
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }

    @staticmethod
    def _response(body, output):
        return {
            "id": "resp_" + uuid.uuid4().hex,
            "object": "response",
            "created_at": int(time.time()),
            "model": body["model"],
            "status": "completed",
            "output": output,
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
