"""Durable Codex identity, exclusive invocation lease, and history checkpoint.

Only hashes and native identifiers are stored here. Codex manages its own
rollout files; this module never fabricates or edits a Codex transcript.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path


class NativeSessionBusy(RuntimeError):
    pass


def default_session_root():
    """Persist independently of process-owned workspaces; override in containers."""
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    if not state.is_absolute():
        state = Path.home() / ".local" / "state"
    return state / "veadk" / "codex" / "sessions"


def content_fingerprint(content):
    return hashlib.sha256(
        json.dumps(
            content.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def scope_key(ctx):
    # JSON encoding avoids delimiter collisions in user-supplied identifiers.
    fields = [
        ctx.session.app_name,
        ctx.session.user_id,
        ctx.session.id,
        ctx.agent.name,
        getattr(ctx, "branch", None),
    ]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


class NativeSession:
    def __init__(self, root, ctx, *, _allow_unfinished=False):
        self.path = Path(root) / scope_key(ctx)
        self.home = str(self.path / "home")
        self.state = {}
        self._lock = None
        self.migration_reason = None
        self._force_migration = None
        self._allow_unfinished = _allow_unfinished
        self._before_invocation = None

    def __enter__(self):
        import fcntl

        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path, 0o700)
        fd = os.open(self.path / "lease", os.O_CREAT | os.O_RDWR, 0o600)
        self._lock = os.fdopen(fd, "w")
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            state_path = self.path / "state.json"
            if state_path.exists():
                self.state = json.loads(state_path.read_text())
                if self.state.get("version") != 1:
                    raise RuntimeError("Unsupported native session state version")
                if self.state.get("status") == "running" and not self._allow_unfinished:
                    raise RuntimeError(
                        "Native session has an unfinished invocation; reconcile its tool effects before retrying"
                    )
            Path(self.home).mkdir(mode=0o700, exist_ok=True)
        except BaseException as error:
            self._lock.close()
            self._lock = None
            if isinstance(error, BlockingIOError):
                raise NativeSessionBusy(
                    "A Codex invocation already owns this session"
                ) from None
            raise
        return self

    def __exit__(self, *args):
        if self._lock:
            self._lock.close()
            self._lock = None

    @property
    def thread_id(self):
        return self.state.get("thread_id")

    @property
    def usage_before(self):
        return self.state.get("usage", {})

    def invalidate(self, reason):
        self._force_migration = reason

    def begin(self, invocation_id):
        """Persist the lease before resumed ADK tools can execute."""
        self._before_invocation = copy.deepcopy(self.state)
        self.state.update(
            version=1, status="running", phase="setup", invocation_id=invocation_id
        )
        self.state.pop("last_turn_status", None)
        self._write()

    def mark_tool_attempt(self):
        if self.state.get("phase") == "setup":
            self.state["phase"] = "tools"
            self._write()

    def abort_setup(self):
        # A local setup exception before any tool or Codex turn started is
        # known to have no execution effects and can safely be retried.
        if self.state.get("phase") == "setup" and self._before_invocation is not None:
            self.state = self._before_invocation or {"version": 1, "status": "ready"}
            self._write()

    @classmethod
    def reconcile(cls, root, ctx, *, invocation_id, effects_reconciled):
        """Explicit administrative recovery after auditing interrupted effects.

        The caller must reconcile ADK tool receipts and native workspace effects
        first. This API never retries a tool or edits the native rollout.
        """
        if effects_reconciled is not True:
            raise ValueError("Interrupted tool effects must be reconciled first")
        with cls(root, ctx, _allow_unfinished=True) as session:
            if (
                session.state.get("status") != "running"
                or session.state.get("invocation_id") != invocation_id
            ):
                raise ValueError("Recovery must identify the unfinished invocation")
            session.state.update(
                status="ready", invalidate_reason="explicit_effect_reconciliation"
            )
            session._write()

    def prepare(self, contents, *, observed=None):
        from google.adk.models.llm_request import LlmRequest
        from veadk.runtime.codex.translate import build_prompt_from_llm_request

        observed = contents if observed is None else observed
        prefix = [content_fingerprint(c) for c in observed[:-1]]
        previous = self.state.get("contents", [])
        callback_changed_history = [
            content_fingerprint(c) for c in contents[:-1]
        ] != prefix
        reason = self._force_migration or self.state.get("invalidate_reason")
        if callback_changed_history:
            reason = "before_model_history_changed"
        if self.thread_id and prefix != previous:
            reason = reason or "adk_history_changed"
        if not self.thread_id and len(contents) > 1:
            reason = reason or "adk_history_import"
        self.migration_reason = reason
        if reason:
            self.state.pop("thread_id", None)
            self.state["usage"] = {}
        selected = contents if reason else contents[-1:]
        if not reason and selected:
            texts = [
                part.text
                for part in selected[0].parts or []
                if part.text is not None and not part.thought
            ]
            if texts:
                return "\n".join(texts)
        return build_prompt_from_llm_request(LlmRequest(contents=selected))

    def started(self, thread_id, invocation_id):
        self.state.update(
            version=1,
            thread_id=thread_id,
            invocation_id=invocation_id,
            status="running",
            phase="native",
            migration_reason=self.migration_reason,
        )
        self._write()

    def commit(self, contents, usage, *, invalidate_reason=None):
        self.state.update(
            version=1,
            status="ready",
            contents=[content_fingerprint(c) for c in contents],
            usage=usage,
            invalidate_reason=invalidate_reason,
        )
        self._write()

    def _write(self):
        target = self.path / "state.json"
        temporary = self.path / "state.json.tmp"
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(self.state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def turn_usage(self, latest):
        total = latest.get("total") or latest.get("last") or {}
        before = self.usage_before
        return {
            "total": {
                key: max(0, value - before.get(key, 0))
                for key, value in total.items()
                if isinstance(value, int)
            }
        }
