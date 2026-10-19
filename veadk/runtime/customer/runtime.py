"""Registered customer execution with durable ownership and display recovery."""

from __future__ import annotations

import hashlib
import json
from contextlib import aclosing
from dataclasses import replace

import anyio

from veadk.runtime.base_runtime import BaseRuntime

from .client import CustomerChannelClient
from .config import check_customer_agent
from .dispatch import CustomerToolDispatcher
from .events import CustomerAdkEventStream
from .protocol import CustomerChannelError, CustomerRunRequest


def _event_payload(event):
    # ADK stamps workflow bookkeeping after the Runtime yields. It does not
    # own the projected identity, display content, actions or usage accounting.
    return event.model_dump(mode="json", exclude={"node_info", "output"})


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


def _new_message(ctx):
    try:
        message = ctx.user_content.model_dump(mode="json", exclude_none=True)
        if (
            set(message) != {"role", "parts"}
            or message["role"] != "user"
            or not message["parts"]
            or any(
                set(part) != {"text"} or not isinstance(part["text"], str)
                for part in message["parts"]
            )
            or not any(part["text"].strip() for part in message["parts"])
        ):
            raise ValueError
    except Exception:
        raise CustomerChannelError("unsupported_user_message") from None
    return message


class CustomerRuntime(BaseRuntime):
    """Use the managed Host for reasoning and ADK for local display storage."""

    name = "customer"

    async def run_async(self, agent, ctx):
        check_customer_agent(agent, getattr(ctx, "run_config", None))
        config = replace(agent.customer_runtime_config)
        if getattr(ctx.plugin_manager, "plugins", ()):
            raise CustomerChannelError("unsupported_customer_plugins")
        message = _new_message(ctx)
        identity = _identity(ctx)
        try:
            with anyio.fail_after(config.total_timeout):
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
                        headers=config.headers,
                        transport=config.transport,
                        on_affinity=lease.set_affinity,
                        operation_timeout=config.operation_timeout,
                        turn_timeout=config.total_timeout,
                        cleanup_timeout=config.cleanup_timeout,
                    ) as client:
                        client.restore_session(
                            binding.remote_app,
                            binding.remote_user,
                            binding.remote_session,
                            affinity=lease.affinity,
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
                        if lease.affinity is None:
                            raise CustomerChannelError("missing_affinity")
                        request = CustomerRunRequest(
                            app_name=binding.remote_app,
                            user_id=binding.remote_user,
                            session_id=binding.remote_session,
                            new_message=message,
                            agent_config=config.agent_config,
                            environment=dict(config.environment),
                            tools=config.tools,
                            skills=config.skills,
                            run_id=turn.run_id,
                            channel_id=turn.channel_id,
                            scope_id=turn.scope_id,
                        )
                        dispatcher = CustomerToolDispatcher(
                            client,
                            request,
                            config.executors,
                            max_concurrency=config.max_concurrency,
                            event_queue_size=config.event_queue_size,
                            cleanup_timeout=config.cleanup_timeout,
                        )
                        async with CustomerAdkEventStream(
                            dispatcher,
                            author=agent.name,
                            invocation_id=ctx.invocation_id,
                            new_message=message,
                            branch=ctx.branch,
                        ) as projection:
                            async with aclosing(projection.events()) as events:
                                async for event in events:
                                    if not event.partial:
                                        await lease.append_event(event)
                                        if event.turn_complete:
                                            await lease.complete_turn()
                                    yield event
                        # ADK's consumer can persist after this task finishes.
                        # Keep completed pending until the next read-back.
        except TimeoutError:
            raise CustomerChannelError("customer_runtime_timeout") from None

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
