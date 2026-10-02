"""Native setup failures must release owned services and session leases."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from veadk.runtime.codex.config import CodexRuntimeConfig
from veadk.runtime.codex.runtime import CodexRuntime


def test_default_native_session_root_survives_process_workspace_lifetime(
    monkeypatch, tmp_path
):
    from veadk.runtime.codex import native_session

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert (
        native_session.default_session_root()
        == tmp_path / "state" / "veadk" / "codex" / "sessions"
    )


@pytest.mark.asyncio
async def test_workspace_setup_failure_closes_native_bridge(monkeypatch):
    from veadk.runtime.codex import native_bridge, runtime

    bridge = SimpleNamespace(
        start=AsyncMock(), stop=AsyncMock(), url="http://127.0.0.1:1"
    )
    monkeypatch.setattr(native_bridge, "NativeBridge", lambda *a, **k: bridge)

    def fail(*args):
        raise OSError("synthetic workspace unavailable")

    monkeypatch.setattr(runtime, "_prepare_workspace", fail)
    agent = SimpleNamespace(
        model_name="synthetic",
        model_api_base="http://127.0.0.1:1",
        model_api_key="synthetic",
        codex_runtime_config=CodexRuntimeConfig(integration_mode="native"),
    )
    with pytest.raises(OSError, match="workspace unavailable"):
        async for _ in CodexRuntime()._run_async(
            agent, SimpleNamespace(), native_session=SimpleNamespace()
        ):
            pass
    bridge.stop.assert_awaited_once()
