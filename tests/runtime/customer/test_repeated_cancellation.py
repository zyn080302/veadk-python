"""Repeated caller cancellation must not bypass bounded owned cleanup."""

import asyncio
import json

import httpx
import pytest

from veadk.runtime.customer import CustomerChannelClient, CustomerChannelError
from veadk.runtime.customer import CustomerToolDispatcher
from tests.runtime.customer.test_channel import call, request, tool
from tests.runtime.customer.test_dispatch import Host, consume


@pytest.mark.asyncio
async def test_repeated_consumer_cancel_joins_before_client_close():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started, cleaning, release = (asyncio.Event() for _ in range(3))

    async def executor(arguments, request_id):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    client = host.client()
    dispatch = CustomerToolDispatcher(client, run, {"lookup": executor})

    async def run_owned():
        async with client:
            await consume(dispatch)

    task = asyncio.create_task(run_owned())
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        closed_before_tool = client._closed
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert not closed_before_tool
        assert dispatch.quiescent and host.stream.closed
        assert host.cancelled == 1 and not host.results
    finally:
        release.set()
        await asyncio.gather(task, dispatch._owner, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["cancel_http", "response_close", "pool_close"])
async def test_repeated_cancel_finishes_channel_and_pool_cleanup(stage):
    run = request()
    host = Host(run, [])
    started, cleaning, release = (asyncio.Event() for _ in range(3))
    order = []

    async def pause(selected):
        if stage == selected:
            cleaning.set()
            await release.wait()

    original_close = host.stream.aclose

    async def close_response():
        await pause("response_close")
        await original_close()
        order.append("response_closed")

    host.stream.aclose = close_response

    async def handle(req):
        if req.url.path.endswith("/messages"):
            assert json.loads(req.content)["type"] == "run.cancel"
            await pause("cancel_http")
            order.append("host_cancelled")
        return await host.handle(req)

    class Transport(httpx.MockTransport):
        async def aclose(self):
            await pause("pool_close")
            order.append("pool_closed")
            await super().aclose()

    client = CustomerChannelClient(
        "https://runtime.invalid", transport=Transport(handle), cleanup_timeout=1
    )

    async def run_owned():
        async with client:
            async with client.run(run) as channel:
                async for _ in channel.events():
                    started.set()
                    await asyncio.Event().wait()

    task = asyncio.create_task(run_owned())
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert order == ["host_cancelled", "response_closed", "pool_closed"]
        assert host.cancelled == 1 and host.stream.closed
        assert client._headers_provider is None and client._affinity is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
async def test_repeated_cancel_does_not_extend_join_budget_or_accept_late_result():
    run = request(tools=(tool(),))
    host = Host(run, [call(run)])
    started, release = asyncio.Event(), asyncio.Event()

    async def executor(arguments, request_id):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return {"late": True}

    async with host.client() as client:
        dispatch = CustomerToolDispatcher(
            client, run, {"lookup": executor}, cleanup_timeout=0.1
        )
        task = asyncio.create_task(consume(dispatch))
        try:
            await asyncio.wait_for(started.wait(), 1)
            began = asyncio.get_running_loop().time()
            task.cancel()
            while not task.done() and asyncio.get_running_loop().time() - began < 0.4:
                await asyncio.sleep(0.005)
                task.cancel()
            assert task.done()
            assert asyncio.get_running_loop().time() - began < 0.3
            with pytest.raises((asyncio.CancelledError, CustomerChannelError)):
                await task
        finally:
            release.set()
            await asyncio.gather(
                task, dispatch._owner, *dispatch._children, return_exceptions=True
            )
        assert dispatch.quiescent and not host.results and host.cancelled == 1
