# Customer session store

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-session-store/README.zh.md)

Component: runtime-customer-session-store. Revised: 2026-10-20. Status: active.
Owner: /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/session_store.py. Tests: /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/customer/test_session_store.py.

- CON-1: `CustomerSessionStore(engine)` reuses a caller-owned AsyncEngine with echo disabled and hide_parameters=True. `initialize()` explicitly creates separate session/turn/event tables. SQLAlchemy failures become `store_unavailable`; cancellation propagates. No implicit network or schema initialization.
- CON-2: `claim(local_identity, engine_id, remote_app, lease_seconds=180)` takes a trusted app/user/session tuple and stores its digest. It does not authenticate the caller. Engine ID is a server configuration revision; remote_app accepts managed_* or studio_debug. Remote user/session IDs are generated once. Rebinding is rejected. Unexpired ownership is `session_busy`, expired unreleased ownership is `session_recovery_required`, never automatically taken over.
- CON-3: State is idle → running → completed → idle. Every mutation checks owner, revision and deadline atomically. `close()` is idempotent; releasing running yields blocked. Expired release cannot restore execution. Completed turns may be released/reclaimed for display recovery. No force-unlock, automatic renewal or retry.
- CON-4: `begin_turn(invocation_id, input_digest)` reserves IDs before remote submission and returns stable run/channel/scope. Repeating an invocation yields `duplicate_turn`; changed input yields `invocation_conflict`. IDs persist until explicit business retention cleanup.
- CON-5: `append_event(event)` journals trusted projected local complete Events before outer display/persistence. Reject partials. Defaults: 1 MiB/event, 4096 events/turn, 16 MiB/turn, configurable positive finite limits. Same ID/payload is idempotent; changed payload is `event_conflict`. Caller must never import remote actions/state.
- CON-6: `complete_turn()` follows verified remote success, tool ACKs and cleanup, and requires a final tool-free text Event with turn_complete=True. `read_completed(invocation_id)` returns display Events without execution. `acknowledge_display()` follows verified ADK persistence and permits another turn while retaining deduplication records.
- CON-7: `set_affinity(SecretStr | None)` persists private routing state; lease, binding and turn repr omit values. Affinity stays outside ordinary state, Events and logs. Not a content secret filter. Caller owns authorization, encryption, safe logging, retention and engine disposal.
- CON-8: Set lease lifetime to cover execution, cleanup and persistence. Uncertain or expired turns require business investigation and a new session or a dedicated recovery procedure, not speculative replay. Cross-process exclusion does not guarantee exactly-once external effects.

SQLite restart/race tests establish local persistence behavior. PostgreSQL integration and formal Runtime/business wiring are not yet verified. No frontend/CLI/deployment change. Design and actual verification are owned by [the change record](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/runtime-customer-session-store/2026-10-20-customer-session-store.md).

The lease exposes `pending_invocation_id` so recovery can locate the persisted turn after restart. Journals use one row per event; appends do not rewrite preceding events. The operation timeout includes waiting for the local writer lock. Non-JSON state and interactive authentication/confirmation events are rejected before serialization; database DEBUG row logging is refused at each operation.

Example of locating completed display after restart; this does not start a customer Runtime. Run inside an async function.

```python
from sqlalchemy.ext.asyncio import create_async_engine
from veadk.runtime.customer import CustomerSessionStore

engine = create_async_engine(
    "sqlite+aiosqlite:////tmp/customer-session-example.sqlite",
    hide_parameters=True,
)
store = CustomerSessionStore(engine)
await store.initialize()
async with await store.claim(
    ("example_app", "user_a", "session_a"),
    engine_id="customer-v1",
    remote_app="managed_example",
) as lease:
    if lease.pending_invocation_id is not None:
        events = await lease.read_completed(lease.pending_invocation_id)
        # Persist/deduplicate events in the local Session before acknowledging.
        # Incomplete turns raise instead of permitting remote replay.
    # Only after verified display persistence: await lease.acknowledge_display()
await engine.dispose()
```


`CustomerSessionStore.operation_timeout` exposes the database operation budget for lease sizing. `CustomerSessionLease.has_turns()` checks for any reserved attempt, including incomplete attempts, so a Runtime cannot recreate missing remote history. No table/schema change.


## Repeated cancellation cleanup (2026-10-20)

CON-3: Lease release resists repeated caller cancellation within the store operation budget, including lock wait; then cancellation propagates. Releasing an uncertain run still blocks reuse.

[Design](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-repeated-cancellation/2026-10-20-customer-repeated-cancellation.md)
