"""Registered customer execution with durable ownership and display recovery."""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import aclosing
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import anyio

from veadk.runtime.base_runtime import BaseRuntime

from .client import CustomerChannelClient
from .config import check_customer_agent
from .dispatch import CustomerToolDispatcher
from .events import CustomerAdkEventStream
from .messages import NATIVE_INITIAL_REQUEST_BYTES, validate_user_message
from .protocol import CustomerChannelError, CustomerRunRequest


def _event_payload(event):
    # ADK stamps workflow bookkeeping after the Runtime yields. It does not
    # own the projected identity, display content, actions or usage accounting.
    return event.model_dump(mode="json", exclude={"node_info", "output"})


class _DisplayClock:
    """Order local publication at the database's datetime resolution."""

    def __init__(self, session):
        self.last = datetime.fromtimestamp(
            max((event.timestamp for event in session.events), default=0),
            tz=timezone.utc,
        )

    def next_timestamp(self):
        now = datetime.fromtimestamp(time.time(), tz=timezone.utc)
        self.last = max(now, self.last + timedelta(microseconds=1))
        return self.last.timestamp()


async def _read_session(service, identity, timeout):
    try:
        with anyio.fail_after(timeout):
            session = await service.get_session(
                app_name=identity[0], user_id=identity[1], session_id=identity[2]
            )
    except Exception:
        raise CustomerChannelError("display_store_unavailable") from None
    if session is None:
        raise CustomerChannelError("display_session_missing")
    return session


def _saved_prefix(journal, session):
    ids = {event.id for event in journal}
    saved = [event for event in session.events if event.id in ids]
    if len(saved) > len(journal) or any(
        _event_payload(actual) != _event_payload(expected)
        for actual, expected in zip(saved, journal)
    ):
        raise CustomerChannelError("display_conflict")
    return len(saved)


async def _acknowledge_if_saved(lease, service, identity, timeout):
    invocation = lease.pending_invocation_id
    if invocation is None:
        return
    journal = await lease.read_completed(invocation)
    session = await _read_session(service, identity, timeout)
    if _saved_prefix(journal, session) != len(journal):
        raise CustomerChannelError("display_recovery_required")
    await lease.acknowledge_display()


def _identity(ctx):
    return ctx.session.app_name, ctx.session.user_id, ctx.session.id


def _new_message(ctx, *, attachments=False):
    try:
        message = ctx.user_content.model_dump(mode="json", exclude_none=True)
        return validate_user_message(message, attachments=attachments)
    except Exception:
        raise CustomerChannelError("unsupported_user_message") from None


class CustomerRuntime(BaseRuntime):
    """Use the managed Host for reasoning and ADK for local display storage."""

    name = "customer"

    async def run_async(self, agent, ctx):
        check_customer_agent(agent, getattr(ctx, "run_config", None))
        config = replace(agent.customer_runtime_config)
        if getattr(ctx.plugin_manager, "plugins", ()):
            raise CustomerChannelError("unsupported_customer_plugins")
        message = _new_message(ctx, attachments=config.protocol == "native")
        identity = _identity(ctx)
        bridge = None
        try:
            with anyio.fail_after(config.total_timeout):
                if config.native_tools:
                    from .native_tools import _NativeToolBridge

                    bridge = _NativeToolBridge(agent, ctx, config.tools)
                async with await config.store.claim(
                    identity,
                    engine_id=config._binding_id,
                    remote_app=config.remote_app,
                    lease_seconds=config.total_timeout
                    + 2 * config.cleanup_timeout
                    + 2 * config.store.operation_timeout
                    + 10,
                ) as lease:
                    await _acknowledge_if_saved(
                        lease, ctx.session_service, identity, config.operation_timeout
                    )
                    display_clock = _DisplayClock(ctx.session)
                    has_turns = await lease.has_turns()
                    if not has_turns and any(
                        event.author != "user"
                        or event.invocation_id != ctx.invocation_id
                        for event in ctx.session.events
                    ):
                        raise CustomerChannelError("legacy_session_requires_migration")
                    binding = lease.binding
                    # Validation/client construction is local, before reservation.
                    async with CustomerChannelClient(
                        config.endpoint,
                        protocol=config.protocol,
                        headers=config.headers,
                        transport=config.transport,
                        on_affinity=lease.set_affinity,
                        operation_timeout=config.operation_timeout,
                        turn_timeout=config.total_timeout,
                        cleanup_timeout=config.cleanup_timeout,
                        max_initial_request_bytes=NATIVE_INITIAL_REQUEST_BYTES
                        if config.protocol == "native"
                        else None,
                    ) as client:
                        client.restore_session(
                            binding.remote_app,
                            binding.remote_user,
                            binding.remote_session,
                            affinity=lease.affinity,
                        )
                        request = CustomerRunRequest(
                            app_name=binding.remote_app,
                            user_id=binding.remote_user,
                            session_id=binding.remote_session,
                            new_message=message,
                            agent_config=config.agent_config,
                            environment=dict(config.environment),
                            tools=config.tools,
                            skills=config.skills,
                        )
                        if config.protocol == "native":
                            from .client import _encode
                            from .native_channel import _native_payload

                            _encode(
                                _native_payload(request, message),
                                client._initial_request_limit,
                            )
                        digest = hashlib.sha256(
                            json.dumps(
                                message, sort_keys=True, ensure_ascii=False
                            ).encode()
                        ).hexdigest()
                        turn = await lease.begin_turn(ctx.invocation_id, digest)
                        if not has_turns:
                            exists = await client.session_exists(
                                binding.remote_app,
                                binding.remote_user,
                                binding.remote_session,
                            )
                            if not exists:
                                await client.create_session(
                                    binding.remote_app,
                                    binding.remote_user,
                                    binding.remote_session,
                                )
                        # Continuations use the Host's session-required run
                        # contract; no GET that downloads reasoning history.
                        if config.protocol == "shared" and lease.affinity is None:
                            raise CustomerChannelError("missing_affinity")
                        request = request.model_copy(
                            update={
                                "run_id": turn.run_id,
                                "channel_id": turn.channel_id,
                                "scope_id": turn.scope_id,
                            }
                        )
                        dispatcher = CustomerToolDispatcher(
                            client,
                            request,
                            bridge.executors
                            if bridge is not None
                            else config.executors,
                            max_concurrency=config.max_concurrency,
                            event_queue_size=config.event_queue_size,
                            cleanup_timeout=config.cleanup_timeout,
                        )
                        if bridge is not None:
                            bridge.sink = dispatcher._emit_local
                        async with CustomerAdkEventStream(
                            dispatcher,
                            author=agent.name,
                            invocation_id=ctx.invocation_id,
                            new_message=message,
                            branch=ctx.branch,
                            local_tools=frozenset(bridge.tools)
                            if bridge is not None
                            else frozenset(),
                        ) as projection:
                            async with aclosing(projection.events()) as events:
                                async for event in events:
                                    if not event.partial:
                                        # Async producers construct events before
                                        # their batches can be published. Stamp
                                        # once here so DB readback and the journal
                                        # retain exactly the same display order.
                                        event.timestamp = display_clock.next_timestamp()
                                        await lease.append_event(event)
                                        if event.turn_complete:
                                            await lease.complete_turn()
                                    yield event
                        # ADK's consumer can persist after this task finishes.
                        # Keep completed pending until the next read-back.
        except TimeoutError:
            raise CustomerChannelError("customer_runtime_timeout") from None
        finally:
            if bridge is not None:
                bridge.close()

    async def recover_display(self, agent, session_service, local_identity):
        """Append only missing completed display; never contact the Host."""
        check_customer_agent(agent)
        config = replace(agent.customer_runtime_config)
        try:
            with anyio.fail_after(config.total_timeout):
                async with await config.store.claim(
                    local_identity,
                    engine_id=config._binding_id,
                    remote_app=config.remote_app,
                    lease_seconds=config.total_timeout
                    + 2 * config.store.operation_timeout
                    + 10,
                ) as lease:
                    if lease.pending_invocation_id is None:
                        return 0
                    journal = await lease.read_completed(lease.pending_invocation_id)
                    session = await _read_session(
                        session_service, local_identity, config.operation_timeout
                    )
                    prefix = _saved_prefix(journal, session)
                    if prefix < len(journal) and any(
                        event.invocation_id != lease.pending_invocation_id
                        and event.timestamp > journal[0].timestamp
                        for event in session.events
                    ):
                        raise CustomerChannelError("display_recovery_order_conflict")
                    for event in journal[prefix:]:
                        try:
                            with anyio.fail_after(config.operation_timeout):
                                await session_service.append_event(
                                    session=session, event=event
                                )
                        except Exception:
                            raise CustomerChannelError(
                                "display_store_unavailable"
                            ) from None
                    await _acknowledge_if_saved(
                        lease, session_service, local_identity, config.operation_timeout
                    )
                    return len(journal) - prefix
        except TimeoutError:
            raise CustomerChannelError("customer_runtime_timeout") from None
