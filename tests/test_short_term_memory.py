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

import asyncio
import importlib
import os

import pytest

from veadk.memory.short_term_memory import ShortTermMemory
from veadk.utils.misc import formatted_timestamp


def test_short_term_memory_local():
    memory = ShortTermMemory(backend="local")
    asyncio.run(
        memory.session_service.create_session(
            app_name="app", user_id="user", session_id="session"
        )
    )
    session = asyncio.run(
        memory.session_service.get_session(
            app_name="app", user_id="user", session_id="session"
        )
    )
    assert session is not None


def test_short_term_memory_sqlite():
    # Every non-`local` backend goes through ADK's DatabaseSessionService, whose
    # async engine runs the sync DBAPI inside a greenlet. SQLAlchemy declares
    # greenlet only for a fixed platform_machine list (aarch64/x86_64/amd64/
    # win32) that excludes macOS arm64, so a plain `pip install veadk-python`
    # leaves it missing there; `sqlalchemy[asyncio]` requires it unconditionally
    # and is what veadk-python[extensions] pulls in transitively (via
    # llama-index-core). On Linux/Windows CI runners it is always present, so
    # this never skips there.
    pytest.importorskip(
        "greenlet",
        reason=(
            "SQLAlchemy's async engine needs greenlet: "
            'pip install "sqlalchemy[asyncio]" '
            '(also pulled in by "veadk-python[extensions]")'
        ),
    )

    memory = ShortTermMemory(
        backend="sqlite",
        local_database_path=f"/tmp/tmp_for_test_{formatted_timestamp()}.db",
    )
    asyncio.run(
        memory.session_service.create_session(
            app_name="app", user_id="user", session_id="session"
        )
    )
    session = asyncio.run(
        memory.session_service.get_session(
            app_name="app", user_id="user", session_id="session"
        )
    )
    assert session is not None
    assert os.path.exists(memory.local_database_path)
    os.remove(memory.local_database_path)


def test_after_create_session_callback_only_runs_for_new_session():
    created_session_ids = []

    def after_create_session(session):
        created_session_ids.append(session.id)

    memory = ShortTermMemory(
        backend="local",
        after_create_session_callback=after_create_session,
    )

    first_session = asyncio.run(
        memory.create_session(app_name="app", user_id="user", session_id="session")
    )
    second_session = asyncio.run(
        memory.create_session(app_name="app", user_id="user", session_id="session")
    )

    assert first_session is not None
    assert second_session is not None
    assert created_session_ids == ["session"]


def test_after_create_session_callback_supports_async_callback():
    created_session_ids = []

    async def after_create_session(session):
        await asyncio.sleep(0)
        created_session_ids.append(session.id)

    memory = ShortTermMemory(
        backend="local",
        after_create_session_callback=after_create_session,
    )

    asyncio.run(
        memory.create_session(app_name="app", user_id="user", session_id="session")
    )

    assert created_session_ids == ["session"]


def test_after_create_session_callback_error_is_propagated():
    def after_create_session(_session):
        raise RuntimeError("callback failed")

    memory = ShortTermMemory(
        backend="local",
        after_create_session_callback=after_create_session,
    )

    with pytest.raises(RuntimeError, match="callback failed"):
        asyncio.run(
            memory.create_session(app_name="app", user_id="user", session_id="session")
        )


def test_existing_session_service_is_reused_and_not_serialized():
    from google.adk.sessions import InMemorySessionService

    service = InMemorySessionService()
    memory = ShortTermMemory(session_service=service)
    assert memory.session_service is service
    assert "session_service" not in memory.model_dump(by_alias=True)
    assert "session_service_override" not in memory.model_dump()
    assert "InMemorySessionService" not in repr(memory)
    asyncio.run(memory.create_session(app_name="app", user_id="user", session_id="s"))
    assert asyncio.run(
        service.get_session(app_name="app", user_id="user", session_id="s")
    )


@pytest.mark.parametrize(
    "options",
    [
        {"backend": "sqlite"},
        {"db_url": "sqlite+aiosqlite:///:memory:"},
        {"db_kwargs": {"pool_pre_ping": True}},
        {"backend_configs": {"host": "unused"}},
        {"local_database_path": "/tmp/unused-injected-storage.sqlite"},
    ],
)
def test_injected_session_service_rejects_conflicting_storage(options):
    from google.adk.sessions import InMemorySessionService

    with pytest.raises(ValueError, match="session_service"):
        ShortTermMemory(session_service=InMemorySessionService(), **options)


def test_database_create_and_resume_do_not_enumerate_or_log_url(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    # Existing public constructor exercises the baseline scan/logging defect.
    path = tmp_path / "synthetic-connection-marker.sqlite"
    memory = ShortTermMemory(db_url=f"sqlite+aiosqlite:///{path}")
    lookup = AsyncMock(wraps=memory.session_service.get_session)
    scan = AsyncMock(side_effect=AssertionError("session hot path enumerated history"))
    monkeypatch.setattr(memory.session_service, "get_session", lookup)
    monkeypatch.setattr(memory.session_service, "list_sessions", scan)
    logs = []
    module = importlib.import_module("veadk.memory.short_term_memory")
    for level in ("debug", "info", "warning", "error"):
        monkeypatch.setattr(
            module.logger, level, lambda message: logs.append(str(message))
        )

    async def exercise():
        try:
            first = await memory.create_session(
                app_name="app", user_id="user", session_id="s"
            )
            again = await memory.create_session(
                app_name="app", user_id="user", session_id="s"
            )
            assert first.id == again.id == "s"
            assert lookup.await_count == 2
            scan.assert_not_awaited()
            assert all(str(path) not in row for row in logs)
        finally:
            await memory.session_service.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "error", [RuntimeError("storage unavailable"), asyncio.CancelledError()]
)
def test_injected_session_lookup_failure_does_not_create(error, monkeypatch):
    from google.adk.sessions import InMemorySessionService
    from unittest.mock import AsyncMock

    service = InMemorySessionService()
    monkeypatch.setattr(service, "get_session", AsyncMock(side_effect=error))
    create = AsyncMock()
    monkeypatch.setattr(service, "create_session", create)
    memory = ShortTermMemory(session_service=service)
    with pytest.raises(type(error)):
        asyncio.run(
            memory.create_session(app_name="app", user_id="user", session_id="s")
        )
    create.assert_not_awaited()
