"""Persistent native thread identity and incremental ADK history."""

from types import SimpleNamespace

import pytest
from google.genai import types

from veadk.runtime.codex.native_session import NativeSession, NativeSessionBusy


def context(branch=None, user="u"):
    return SimpleNamespace(
        session=SimpleNamespace(app_name="a", user_id=user, id="s"),
        agent=SimpleNamespace(name="agent"),
        branch=branch,
    )


def content(role, text):
    return types.Content(role=role, parts=[types.Part(text=text)])


def test_native_session_resume_incremental_and_isolated(tmp_path):
    first = content("user", "first")
    answer = content("model", "answer")
    second = content("user", "second")
    with NativeSession(tmp_path, context()) as session:
        assert session.prepare([first]) == "first"
        session.started("native-thread-1", "inv-1")
        session.commit([first, answer], {"input_tokens": 11})
        with pytest.raises(NativeSessionBusy):
            with NativeSession(tmp_path, context()):
                pass
        with NativeSession(tmp_path, context(branch="other")) as other:
            assert other.home != session.home
            assert other.thread_id is None
        with NativeSession(tmp_path, context(user="other")) as other:
            assert other.home != session.home
    with NativeSession(tmp_path, context()) as resumed:
        assert resumed.thread_id == "native-thread-1"
        assert resumed.prepare([first, answer, second]) == "second"
        assert resumed.migration_reason is None
        assert resumed.usage_before == {"input_tokens": 11}


def test_history_edit_and_missing_state_are_explicit_migrations(tmp_path):
    first, answer = content("user", "first"), content("model", "answer")
    with NativeSession(tmp_path, context()) as session:
        prompt = session.prepare([first, answer, content("user", "next")])
        assert session.migration_reason == "adk_history_import"
        assert "answer" in prompt
        session.started("native-thread-1", "inv-1")
        session.commit([first, answer], {})
    with NativeSession(tmp_path, context()) as session:
        prompt = session.prepare(
            [first, content("model", "edited"), content("user", "next")]
        )
        assert session.migration_reason == "adk_history_changed"
        assert session.thread_id is None
        assert "edited" in prompt


def test_unfinished_invocation_is_not_automatically_replayed(tmp_path):
    with NativeSession(tmp_path, context()) as session:
        session.started("native-thread-1", "inv-1")
    with pytest.raises(RuntimeError, match="unfinished"):
        with NativeSession(tmp_path, context()):
            pass


def test_recovery_requires_exact_invocation_and_effect_reconciliation(tmp_path):
    with NativeSession(tmp_path, context()) as session:
        session.started("native-thread-1", "inv-1")
    with pytest.raises(ValueError, match="reconciled"):
        NativeSession.reconcile(
            tmp_path, context(), invocation_id="inv-1", effects_reconciled=False
        )
    with pytest.raises(ValueError, match="invocation"):
        NativeSession.reconcile(
            tmp_path, context(), invocation_id="different", effects_reconciled=True
        )
    NativeSession.reconcile(
        tmp_path, context(), invocation_id="inv-1", effects_reconciled=True
    )
    with NativeSession(tmp_path, context()) as recovered:
        assert recovered.prepare([content("user", "continue after reconciliation")])
        assert recovered.thread_id is None
        assert recovered.migration_reason == "explicit_effect_reconciliation"
