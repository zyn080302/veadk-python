"""Durable exclusion and display recovery; never replay uncertain execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import anyio
from pydantic import SecretStr
from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from .cleanup import _run_cleanup
from .protocol import CustomerChannelError

_metadata = MetaData()
_sessions = Table(
    "veadk_customer_sessions_v1",
    _metadata,
    Column("key", String(64), primary_key=True),
    Column("engine_id", String(128), nullable=False),
    Column("remote_app", String(128), nullable=False),
    Column("remote_user", String(64), nullable=False),
    Column("remote_session", String(64), nullable=False),
    Column("owner", String(32)),
    Column("deadline", Float, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("current_invocation", String(256)),
    Column("affinity", Text),
)
_turns = Table(
    "veadk_customer_turns_v1",
    _metadata,
    Column("session_key", String(64), primary_key=True),
    Column("invocation_id", String(256), primary_key=True),
    Column("input_digest", String(64), nullable=False),
    Column("run_id", String(32), nullable=False),
    Column("channel_id", String(32), nullable=False),
    Column("scope_id", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("event_count", Integer, nullable=False),
    Column("event_bytes", Integer, nullable=False),
)
_journal = Table(
    "veadk_customer_events_v1",
    _metadata,
    Column("session_key", String(64), primary_key=True),
    Column("invocation_id", String(256), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("event_id", String(128), nullable=False),
    Column("payload", Text, nullable=False),
    UniqueConstraint("session_key", "invocation_id", "event_id"),
)


def _identifier(value, limit):
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
    )


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _key(identity):
    if (
        not isinstance(identity, tuple)
        or len(identity) != 3
        or not all(_identifier(v, 256) for v in identity)
    ):
        raise ValueError("Invalid trusted session identity")
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, repr=False)
class CustomerSessionBinding:
    """Server-owned remote identity, not browser identity or public state."""

    remote_app: str
    remote_user: str
    remote_session: str


@dataclass(frozen=True, repr=False)
class CustomerTurnRecord:
    """Reserved wire identifiers for exactly one attempted invocation."""

    run_id: str
    channel_id: str
    scope_id: str


class CustomerSessionStore:
    """Use caller-owned SQLite/PostgreSQL storage, with no automatic takeover.

    Initialize explicitly. The caller owns engine disposal, connection and
    statement timeouts, safe logging, authentication and encryption at rest.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        operation_timeout: float = 10,
        max_event_bytes: int = 1024 * 1024,
        max_events: int = 4096,
        max_turn_bytes: int = 16 * 1024 * 1024,
    ):
        if (
            not isinstance(engine, AsyncEngine)
            or engine.echo
            or not engine.sync_engine.hide_parameters
        ):
            raise ValueError("Customer sessions require safe database logging")
        if not _positive(operation_timeout):
            raise ValueError("Invalid store operation timeout")
        for value in (max_event_bytes, max_events, max_turn_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("Invalid journal capacity")
        self._engine = engine
        self._timeout = operation_timeout
        self._event_limit = max_event_bytes
        self._count_limit = max_events
        self._turn_limit = max_turn_bytes
        self._clock = time.time

    @property
    def operation_timeout(self):
        """Database operation budget, including lock wait."""
        return self._timeout

    @asynccontextmanager
    async def _transaction(self, *, claim=False):
        if (
            self._engine.echo
            or not self._engine.sync_engine.hide_parameters
            or self._engine.sync_engine.logger.isEnabledFor(logging.DEBUG)
        ):
            raise CustomerChannelError("unsafe_database_logging")
        try:
            with anyio.fail_after(self._timeout):
                async with self._engine.begin() as connection:
                    yield connection
        except IntegrityError:
            # A concurrent first claim can win the primary-key insertion.
            raise CustomerChannelError(
                "session_busy" if claim else "store_unavailable"
            ) from None
        except (SQLAlchemyError, TimeoutError):
            raise CustomerChannelError("store_unavailable") from None

    async def initialize(self):
        """Create only this component's private tables, using an explicit call."""
        async with self._transaction() as connection:
            await connection.run_sync(_metadata.create_all)

    async def claim(
        self,
        local_identity: tuple[str, str, str],
        *,
        engine_id: str,
        remote_app: str,
        lease_seconds: float = 180,
    ) -> CustomerSessionLease:
        """Reserve a session; expired ownership is never assumed safe to steal."""
        key = _key(local_identity)
        if (
            not _identifier(engine_id, 128)
            or not isinstance(remote_app, str)
            or len(remote_app) > 128
            or not re.fullmatch(r"(?:studio_debug|managed_[A-Za-z0-9_-]+)", remote_app)
            or not _positive(lease_seconds)
        ):
            raise ValueError("Invalid customer session binding")
        owner = uuid4().hex
        async with self._transaction(claim=True) as connection:
            row = (
                (
                    await connection.execute(
                        select(_sessions).where(_sessions.c.key == key)
                    )
                )
                .mappings()
                .first()
            )
            now = self._clock()
            if row is None:
                values = dict(
                    key=key,
                    engine_id=engine_id,
                    remote_app=remote_app,
                    remote_user=uuid4().hex,
                    remote_session=uuid4().hex,
                    owner=owner,
                    deadline=now + lease_seconds,
                    revision=0,
                    status="idle",
                    current_invocation=None,
                    affinity=None,
                )
                await connection.execute(insert(_sessions).values(**values))
            else:
                if row["engine_id"] != engine_id or row["remote_app"] != remote_app:
                    raise CustomerChannelError("engine_mismatch")
                if row["owner"] is not None:
                    raise CustomerChannelError(
                        "session_busy"
                        if row["deadline"] > now
                        else "session_recovery_required"
                    )
                if row["status"] not in {"idle", "completed"}:
                    raise CustomerChannelError("session_recovery_required")
                values = dict(row)
                values.update(
                    owner=owner,
                    deadline=now + lease_seconds,
                    revision=row["revision"] + 1,
                )
                result = await connection.execute(
                    update(_sessions)
                    .where(
                        _sessions.c.key == key,
                        _sessions.c.owner.is_(None),
                        _sessions.c.revision == row["revision"],
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    raise CustomerChannelError("session_busy")
        return CustomerSessionLease(self, values)


class CustomerSessionLease:
    """One revocable DB owner; use async with and acknowledge saved display."""

    def __init__(self, store, row):
        self._store = store
        self._key = row["key"]
        self._owner = row["owner"]
        self._binding = CustomerSessionBinding(
            row["remote_app"], row["remote_user"], row["remote_session"]
        )
        self._affinity = SecretStr(row["affinity"]) if row["affinity"] else None
        self._pending_invocation_id = row["current_invocation"]
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def binding(self):
        return self._binding

    @property
    def affinity(self):
        return self._affinity

    @property
    def pending_invocation_id(self):
        """The persisted invocation requiring completion/display acknowledgement."""
        return self._pending_invocation_id

    async def __aenter__(self):
        if self._closed:
            raise CustomerChannelError("lease_closed")
        return self

    async def __aexit__(self, *_):
        await self.close()

    @asynccontextmanager
    async def _bounded_lock(self):
        try:
            with anyio.fail_after(self._store._timeout):
                async with self._lock:
                    yield
        except TimeoutError:
            raise CustomerChannelError("store_unavailable") from None

    @asynccontextmanager
    async def _change(self, *, allow_expired=False):
        # A single lease may receive concurrent tool/result updates.
        async with self._bounded_lock():
            if self._closed:
                raise CustomerChannelError("lease_closed")
            async with self._store._transaction() as connection:
                row = (
                    (
                        await connection.execute(
                            select(_sessions).where(_sessions.c.key == self._key)
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None or row["owner"] != self._owner:
                    raise CustomerChannelError("lease_revoked")
                now = self._store._clock()
                if not allow_expired and row["deadline"] <= now:
                    raise CustomerChannelError("lease_expired")
                conditions = [
                    _sessions.c.key == self._key,
                    _sessions.c.owner == self._owner,
                    _sessions.c.revision == row["revision"],
                ]
                if not allow_expired:
                    conditions.append(_sessions.c.deadline > now)
                result = await connection.execute(
                    update(_sessions)
                    .where(*conditions)
                    .values(revision=row["revision"] + 1)
                )
                if result.rowcount != 1:
                    raise CustomerChannelError("lease_revoked")
                yield connection, row
                # Expiry while waiting for DB I/O must also roll back the write.
                if not allow_expired and row["deadline"] <= self._store._clock():
                    raise CustomerChannelError("lease_expired")

    async def _session_update(self, connection, **values):
        await connection.execute(
            update(_sessions).where(_sessions.c.key == self._key).values(**values)
        )

    def _turn_filter(self, invocation_id):
        return (
            _turns.c.session_key == self._key,
            _turns.c.invocation_id == invocation_id,
        )

    async def _turn(self, connection, invocation_id):
        return (
            (
                await connection.execute(
                    select(_turns).where(*self._turn_filter(invocation_id))
                )
            )
            .mappings()
            .first()
        )

    async def set_affinity(self, value: SecretStr | None):
        """Store a private response routing value, never ordinary Session state."""
        if value is not None and (
            not isinstance(value, SecretStr)
            or not _identifier(value.get_secret_value(), 8192)
        ):
            raise ValueError("Invalid private affinity")
        async with self._change() as (connection, _):
            await self._session_update(
                connection, affinity=value.get_secret_value() if value else None
            )
        self._affinity = value

    async def begin_turn(
        self, invocation_id: str, input_digest: str
    ) -> CustomerTurnRecord:
        """Reserve before sending anything remotely; never reuse a turn ID."""
        if (
            not _identifier(invocation_id, 256)
            or not isinstance(input_digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", input_digest)
        ):
            raise ValueError("Invalid invocation reservation")
        record = CustomerTurnRecord(uuid4().hex, uuid4().hex, uuid4().hex)
        async with self._change() as (connection, session):
            previous = await self._turn(connection, invocation_id)
            if previous is not None:
                raise CustomerChannelError(
                    "duplicate_turn"
                    if previous["input_digest"] == input_digest
                    else "invocation_conflict"
                )
            if session["status"] == "completed":
                raise CustomerChannelError("display_recovery_required")
            if session["status"] != "idle":
                raise CustomerChannelError("session_recovery_required")
            await connection.execute(
                insert(_turns).values(
                    session_key=self._key,
                    invocation_id=invocation_id,
                    input_digest=input_digest,
                    run_id=record.run_id,
                    channel_id=record.channel_id,
                    scope_id=record.scope_id,
                    status="running",
                    event_count=0,
                    event_bytes=0,
                )
            )
            await self._session_update(
                connection, status="running", current_invocation=invocation_id
            )
        self._pending_invocation_id = invocation_id
        return record

    async def has_turns(self):
        """Whether any remote attempt was reserved, including incomplete ones."""
        async with self._change() as (connection, _):
            result = await connection.execute(
                select(_turns.c.invocation_id)
                .where(_turns.c.session_key == self._key)
                .limit(1)
            )
            return result.first() is not None

    def _journal_filter(self, invocation_id):
        return (
            _journal.c.session_key == self._key,
            _journal.c.invocation_id == invocation_id,
        )

    def _decode(self, payload):
        from google.adk.events import Event

        try:
            if len(payload.encode()) > self._store._event_limit:
                raise ValueError
            return Event.model_validate_json(payload)
        except (ValueError, TypeError, RecursionError):
            raise CustomerChannelError("journal_corrupt") from None

    async def append_event(self, event):
        """Journal a trusted complete local Event before outer persistence."""
        from google.adk.events import Event

        try:
            if (
                not isinstance(event, Event)
                or event.partial
                or event.author == "user"
                or not _identifier(event.id, 128)
                or event.actions.requested_auth_configs
                or event.actions.requested_tool_confirmations
            ):
                raise ValueError
            # Reject non-JSON state before ADK can log a serializer exception
            # or persist a potentially private object representation.
            json.dumps(event.actions.state_delta, allow_nan=False)
            data = event.model_dump(mode="json", exclude_none=True)
            encoded = json.dumps(
                data,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (ValueError, TypeError, RecursionError):
            raise CustomerChannelError("invalid_journal_event") from None
        size = len(encoded.encode())
        if size > self._store._event_limit:
            raise CustomerChannelError("journal_limit")
        async with self._change() as (connection, session):
            invocation = session["current_invocation"]
            if session["status"] != "running" or event.invocation_id != invocation:
                raise CustomerChannelError("invalid_journal_event")
            turn = await self._turn(connection, invocation)
            previous = (
                await connection.execute(
                    select(_journal.c.payload).where(
                        *self._journal_filter(invocation),
                        _journal.c.event_id == event.id,
                    )
                )
            ).scalar_one_or_none()
            if previous is not None:
                if previous != encoded:
                    raise CustomerChannelError("event_conflict")
                return
            last = (
                await connection.execute(
                    select(_journal.c.payload)
                    .where(*self._journal_filter(invocation))
                    .order_by(_journal.c.position.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last is not None and self._decode(last).turn_complete:
                raise CustomerChannelError("event_after_final")
            if (
                turn["event_count"] >= self._store._count_limit
                or turn["event_bytes"] + size > self._store._turn_limit
            ):
                raise CustomerChannelError("journal_limit")
            await connection.execute(
                insert(_journal).values(
                    session_key=self._key,
                    invocation_id=invocation,
                    position=turn["event_count"],
                    event_id=event.id,
                    payload=encoded,
                )
            )
            await connection.execute(
                update(_turns)
                .where(*self._turn_filter(invocation))
                .values(
                    event_count=turn["event_count"] + 1,
                    event_bytes=turn["event_bytes"] + size,
                )
            )

    async def complete_turn(self):
        """Called only after verified remote success, ACKs and tool cleanup."""
        async with self._change() as (connection, session):
            if session["status"] != "running":
                raise CustomerChannelError("invalid_turn_state")
            invocation = session["current_invocation"]
            payload = (
                await connection.execute(
                    select(_journal.c.payload)
                    .where(*self._journal_filter(invocation))
                    .order_by(_journal.c.position.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            last = self._decode(payload) if payload is not None else None
            if (
                last is None
                or last.error_code
                or last.error_message
                or last.interrupted
                or not last.turn_complete
                or not last.is_final_response()
                or last.get_function_calls()
                or last.get_function_responses()
                or not last.content
                or not any(
                    p.text is not None and not p.thought
                    for p in last.content.parts or []
                )
            ):
                raise CustomerChannelError("missing_final_response")
            await connection.execute(
                update(_turns)
                .where(*self._turn_filter(invocation))
                .values(status="completed")
            )
            await self._session_update(connection, status="completed")

    async def read_completed(self, invocation_id: str):
        """Recover only display Events, never remote execution or tool calls."""
        if not _identifier(invocation_id, 256):
            raise ValueError("Invalid invocation identity")
        async with self._change() as (connection, _):
            turn = await self._turn(connection, invocation_id)
            if turn is None or turn["status"] != "completed":
                raise CustomerChannelError("turn_not_completed")
            if (
                not 0 < turn["event_count"] <= self._store._count_limit
                or not 0 < turn["event_bytes"] <= self._store._turn_limit
            ):
                raise CustomerChannelError("journal_corrupt")
            rows = (
                (
                    await connection.execute(
                        select(_journal)
                        .where(*self._journal_filter(invocation_id))
                        .order_by(_journal.c.position)
                        .limit(self._store._count_limit + 1)
                    )
                )
                .mappings()
                .all()
            )
            if (
                len(rows) != turn["event_count"]
                or sum(len(row["payload"].encode()) for row in rows)
                != turn["event_bytes"]
                or any(row["position"] != i for i, row in enumerate(rows))
            ):
                raise CustomerChannelError("journal_corrupt")
            return [self._decode(row["payload"]) for row in rows]

    async def acknowledge_display(self):
        """Permit another turn only after verifying local Session persistence."""
        async with self._change() as (connection, session):
            if session["status"] != "completed":
                raise CustomerChannelError("invalid_turn_state")
            await self._session_update(
                connection, status="idle", current_invocation=None
            )
        self._pending_invocation_id = None

    async def close(self):
        """Relinquish ownership without making uncertain execution reusable."""
        try:
            await _run_cleanup(self._close(), timeout=self._store.operation_timeout)
        except TimeoutError:
            raise CustomerChannelError("store_unavailable") from None

    async def _close(self):
        if self._closed:
            return
        try:
            async with self._change(allow_expired=True) as (connection, session):
                status = (
                    "blocked" if session["status"] == "running" else session["status"]
                )
                await self._session_update(connection, status=status, owner=None)
            self._closed = True
            self._affinity = None
        except CustomerChannelError as error:
            if str(error) != "lease_closed":
                raise
