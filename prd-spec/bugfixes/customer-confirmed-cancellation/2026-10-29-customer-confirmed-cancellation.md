# Confirmed cancellation of a customer turn

[中文](2026-10-29-customer-confirmed-cancellation.zh.md)

Change ID: customer-confirmed-cancellation. Date: 2026-10-29. Status: approved.
Components: [customer Runtime](../../../specs/runtime-customer/README.md), [session store](../../../specs/runtime-customer-session-store/README.md), [dispatch](../../../specs/runtime-customer-tool-dispatch/README.md). No frontend, dependency, deployment credential or provider configuration change.

## Evidence and intent

The current application entry guard and CustomerSessionLease.close both quarantine a running turn after SSE cancellation. The same business identity cannot continue even after expiry. Existing seven application reproductions confirm the defect, not a fix. Closing the local HTTP response alone cannot prove that Host execution stopped. External tool side effects cannot be rolled back.

The goal is continuation using the same authenticated app/user/session and remote binding after a confirmed user disconnect. Crash recovery, timeout takeover, arbitrary force unlock and automatic tool replay are out of scope. Default SDK behavior without an explicit server integration remains conservative.

## Requirements and scenarios

- FR-1: The server observes a real ASGI disconnect. Client headers, task cancellation, deadlines and transport errors alone do not authorize recovery. Cancellation before execution keeps the existing safe release behavior.
- FR-2: Runtime revokes submissions and joins the Dispatcher, tool tasks and HTTP cleanup before invoking an optional server-owned asynchronous cancellation confirmer. A non-quiescent Dispatcher, cleanup failure or repeated cancellation that exhausts cleanup leaves the turn blocked.
- FR-3: The confirmer receives an immutable, repr-safe context identifying the local app/user/session, invocation, remote binding and reserved run; it must return literal True only after remote execution is fenced, stopped and its history settled. SDK never invents remote stop proof. SkyEyes supplies the integration; requests cannot configure it.
- FR-4: Keep complete journal events and original user history; never promote streamed fragments to a successful answer. Restore only a verified saved prefix, close unmatched tool calls with an explicit cancelled/unknown-effect response, and append an interrupted terminal event. Read back and verify the complete terminal journal before allowing a new turn. Conflicting, later or missing history prevents release.
- FR-5: Only the live original owner may settle the original invocation/run. Retain cancelled turn IDs for duplicate prevention. Keep the stable remote binding. A cancelled terminal journal pending persistence can be reclaimed for display recovery, never execution replay.
- FR-6: Ordinary concurrent calls remain session_busy. The application may briefly wait only for a recorded cancellation cleanup by that owner; no expiry stealing. Restart without stop proof remains blocked.
- FR-7: No extra model call, external request or per-event history lookup on a normal successful turn. Cancellation-only work is bounded. No credential, routing capability, raw production log or payload is recorded in the design or cancellation context repr.

## Design and contract changes

Add optional CustomerRuntimeConfig.confirm_cancellation and a frozen CustomerCancellationContext. Wrap the projection within the original lease: after projection and client cleanup, an incomplete exit may run the confirmer in bounded shielded cleanup. The caller integration checks the actual disconnect flag; exceptions or any value other than True cannot restore execution. The bridge is revoked before history settlement.

Add owner-checked CustomerSessionLease terminal-cancellation methods, including reading a running journal, recording a cancelled terminal state and reading completed-or-cancelled display. The existing successful complete_turn validation remains unchanged. The cancellation path verifies the saved journal prefix, appends missing complete events plus unmatched-call responses and an interrupted event, verifies readback, and clears pending state only after acknowledgement. Keep the existing database columns; add the cancelled state to the state contract. An interruption is explicitly not business success. Default recovery APIs remain display-only and never contact the Host.

SkyEyes integration uses an internal loopback cancellation endpoint authenticated by the existing server-created turn capability and exact remote identity. It fences that ticket against new steps, cancels and joins only its registered Host request, verifies Host task cleanup, then settles that Host invocation's unmatched calls and interruption history. Cross-process shared state confirms the fenced terminal step. Missing task/ambiguous state cannot become proof. This is an application contract, not an SDK network protocol or public BFF cancellation endpoint. The external business guard releases only after SDK settlement is confirmed for the same owner and business identity. No customer original Runtime change is authorized.

Alternatives rejected: deleting locks, treating all cancellation as healthy, TTL takeover, creating a replacement session and marking incomplete content complete. They allow overlap, lose context or hide uncertain effects. No distributed exactly-once claim.

## Tasks

- T-1 (FR-1–7): bilingual design/component updates and review; obtain explicit approval of the concrete SDK change before production or test edits.
- T-2 (FR-2–5): failing store and real Runtime regression; then implement config, context, cleanup and terminal journal settlement.
- T-3 (FR-1,3,6): application disconnect marker, exact-ticket Host stop/settlement and business release; add actual ASGI/HTTP regression to mandatory gates.
- T-4 (FR-2–7): fixed wheel/receipt, installed consumer regression, required SDK gates and application API/native/PostgreSQL gates.
- T-5: after all gates, only the authorized PDSA release and live cancellation/followup/history/APMPlus validation. No customer original Runtime writes.

## Acceptance and verification

AC-1: identical pre-fix/post-fix tests reproduce before headers, after an increment and during a tool; same-session followup succeeds only after both owners settle. Assert task exit, no new old-turn model/tool sends, journal pairing, stable identity and normal concurrency refusal.
AC-2: deny callback absent/False/non-bool/error, spoofed disconnect, timeout, noncooperative tools, ambiguous Host, wrong identity/run/owner, expired owner, conflicting saved prefix, late writes and interrupted cleanup. Retain existing default quarantine regression.
AC-3: restart with a pending cancelled terminal journal recovers display without a Host/tool request. A crash-held running owner cannot be stolen. Completed-but-unacknowledged display follows the existing recovery semantics.
AC-4: targeted tests and SDK default Python regression, pre-commit, affected lint/type checks; installed wheel and source digest binding. Application mandatory API/native/PostgreSQL gates must actually execute the new tests. Local simulated results do not prove deployment.
AC-5: on the authorized PDSA formal API, disconnect an in-progress SSE response, immediately follow up with the same identity, read history and compare both real traces for execution overlap and observed cancellation. Keep business quality and collection acceptance separate.

Commands: uv run --extra dev pytest tests/runtime/customer; uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"; uv run --extra dev pre-commit run --all-files. Live Codex smoke only when prepared and separately (CODEX_RUN_SMOKE=1, -p no:xdist).

## Review, risks and delivery status

Direct design review performed because review-spec is unavailable. Checked owner/deadline fences, task cleanup ordering, saved-prefix validation, repeated cancellation, server-only configuration, backward compatibility and bilingual parity. Blocker addressed in design: a boolean callback alone is insufficient without the SkyEyes exact-ticket Host stop contract and the SDK's independently verified Dispatcher/history conditions. User authorized continuing the previously proposed concrete SDK extension on 2026-10-29. Approval recorded before production or test edits. Implementation and targeted offline verification are complete; the default parallel SDK regression is still running. No new wheel or PDSA release yet. Host task termination and ADK persistence across both processes remain implementation/E2E risks; unresolved proof must fail closed.

Integration refinement: the Host assigns invocation IDs before Runner execution, without a normal-path history query. `CustomerSessionStore.cancellation_settled` provides read-only exact-run/identity/engine acknowledgement proof to an outer guard that still owns the business Session. It requires cancelled turn, idle session, no pending display and relinquished SDK owner; it cannot change ownership or execute a request.

Cancellation timing refinement: exercise cancellation while a complete tool response is being journaled, before commit, during commit, and after commit but before publication. Settlement must wait for the original database operation to stop, preserve committed events, and explicitly close rolled-back unmatched calls without replay. A store failure or unconfirmed transaction cleanup still prevents release. The Runtime owns each accepted complete-event journal write as a leaf task and shields it from caller cancellation; cancellation joins that task within the cleanup budget. Only a successfully finished write permits confirmation. A timed-out, cancelled or failed writer prevents settlement. The normal path keeps the existing database calls and bounded operation budget; partial token events do not create a journal task.

Cleanup failure refinement: a lease release failure must not replace an active `CancelledError` or `GeneratorExit` with a new exception. ADK may try to publish that exception to a consumer that has already disconnected and then wait indefinitely for acknowledgement. Preserve cancellation, record only a fixed diagnostic code, and leave the persisted owner/state unchanged when release cannot be confirmed. Normal, non-cancelled release failures still propagate. A same-Runner fault-injection regression must fail before the change and pass after it, while proving that no subsequent execution is authorized.


## Verification checkpoint (2026-10-29)

- Targeted confirmed-cancellation: pass, 8 tests (`.codex/cancellation-targeted-v3.txt`); all customer Runtime tests: pass, 386 tests (`.codex/cancellation-customer-v3.txt`). Same-test pre-fix failure is retained in `.codex/cancellation-red.txt`.
- Affected Ruff and Pyright: pass, zero type errors. Pre-commit: pass, five hooks; newly untracked files still require explicit scanning before commit.
- Default SDK regression: running, `.codex/cancellation-full-v2.txt`; not accepted as pass. The earlier fixture failure and existing unrelated retry failure remain recorded, and that retry passes its targeted rerun.
- Application cross-process HTTP model/tool cancellation: pass, two targeted tests. They assert original work stopped, same identity/history preserved, no tool replay, and ordinary concurrency refused. This fast diagnostic run does not replace full installed-wheel, API/native/PostgreSQL gates.
- Host keeps the first invocation ID across internal deferred-tool requests for one server ticket. It verifies all accepted original/tool inputs before settlement; it never invents missing input after execution. Repeated outer cancellation preserves the cancellation exception but still records stop confirmation when all owned tasks are done.
- New wheel, installed consumer, full application release gates, live PDSA cancellation/followup/history/APMPlus: not_run. Customer original Runtime is frozen.

## Latest checkpoint: PDSA updates paused

The user has paused PDSA Runtime updates. This supersedes the earlier release authorization: T-5 and AC-5 are pending further authorization. No cloud build, Runtime configuration change, restart or release is performed. Local SDK development, artifact verification and isolated offline consumer gates continue. The customer original Runtime remains frozen.

- The previous default SDK run (`.codex/cancellation-full-v2.txt`) ended with 7946 passed, 1 failed, 50 skipped and 4 xfailed. Its failure and diagnostic interruption remain evidence; it is not a passing gate.
- Accepted-journal cancellation and cleanup-exception regressions reproduce before their respective changes. With both changes, the confirmed-cancellation suite passes all 15 tests (`.codex/cancellation-accepted-journal-green-v2.txt`).
- Complete SDK run v3 ended with 7888 passed and 66 failed: its launcher mistakenly set `OTEL_SDK_DISABLED=true`, disabling the in-memory collectors needed by those tests. All 66 previously failed tests and the 15 cancellation regressions pass together after removing that launcher setting (81 passed). Full run v4 (`.codex/cancellation-full-v4.txt`) is now running against the bound 1052-file Python manifest. The v3 failure remains evidence; no production collection logic or test assertion was weakened.
- The test-only keyword-argument typing issue is fixed. Affected Ruff, formatting and Pyright checks pass, with zero type errors; the final pre-commit run passes all five hooks. The preceding failed type-check evidence is retained.
- No new committed SDK wheel, installed consumer result, complete application API/native/PostgreSQL gate or live cancellation acceptance is claimed yet.
