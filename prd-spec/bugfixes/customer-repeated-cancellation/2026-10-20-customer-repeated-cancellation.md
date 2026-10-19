# Customer cleanup under repeated cancellation

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-repeated-cancellation/2026-10-20-customer-repeated-cancellation.zh.md)

ID: customer-repeated-cancellation. Created/revised: 2026-10-20. Status: implemented.

## Evidence and scope

At SDK parent `9e14fe4b`, the business loopback HTTP test cancels `/run_sse` while MCP initialization is pending. The dispatcher join, HTTP pool close and lease release each receive cancellation; the owner then attempts `run.cancel` against an already closed client. AnyIO shielding alone does not protect against direct repeated `asyncio.Task.cancel()`. Generator ownership is already correct and remains in its original task.

This fix completes the authorized customer Runtime adaptation. It covers dispatcher join, channel cancellation/response close, HTTP pool close and lease release. It does not add retries, change tool results, resume uncertain sessions, deploy, or claim live customer acceptance.

## Requirements and scenarios

- FR-1: After caller cancellation, revoke tool submission immediately; further cancellations cannot bypass the bounded owner/children join and cause an early client close. Send at most one `run.cancel` for an incomplete submitted run.
- FR-2: Repeated cancellation during cancel HTTP, response/pool close or lease release must not abort cooperative cleanup. Preserve the existing finite budgets; retries must never reset the deadline. Propagate caller cancellation after cleanup or budget expiry.
- FR-3: Normal completion, cleanup errors/timeouts and noncooperative tools retain explicit behavior. No success event, replay, implicit unlock or late result after cancellation. Running leases become blocked, idle leases can be reclaimed after release.
- FR-4: Keep public signatures, defaults, identity boundaries and dependencies unchanged. Do not transfer live async generators or open AnyIO scopes to another task. No payload/credential diagnostics.

Given an active tool, when the consumer is cancelled repeatedly while that tool cooperatively closes, then the dispatcher joins it, the Host receives one cancellation, and only then may the outer client close. Given a cancellation during lease release, when cleanup completes, then durable ownership is released before the caller returns with cancellation. Given an exhausted cleanup budget, then bounded exit occurs without accepting late results.

## Design and contract impact

Add private cleanup helpers under `veadk/runtime/customer/cleanup.py`: wait for owned tasks with an absolute deadline, AnyIO shielding and deferred direct cancellation; run leaf cleanup operations in a separately owned task so caller cancellation cannot destroy their await chain. Catch direct cancellation only while joining; do not call `uncancel()` or convert it to successful completion. Consume child exceptions, request cancellation once on timeout, and do not wait indefinitely for code that ignores cancellation.

Dispatcher joins existing owner/children without moving their work. Channel close and lease close use bounded leaf tasks created before their first await. Channel cancellation and response close continue sharing one budget (80% reserved for cancellation, remaining time for response close). Pool close retains its separate configured budget. Lease release uses the existing store operation budget including lock wait. Existing async generators/scopes remain in their original task.

Update runtime-customer-tool-dispatch CON-5, runtime-customer-channel CON-6 and runtime-customer-session-store CON-3. No wire/schema, frontend, CLI or dependency changes. A slow or uncooperative transport/database may still fail cleanup; this fix cannot force-stop arbitrary Python code or prove remote rollback. The caller must retain existing quarantine/recovery policy.

Alternatives rejected: adding only AnyIO shielding (already fails direct cancellation), unlimited shielded waits (unbounded resource retention), moving the whole Runtime generator (violates task ownership).

## Tasks and acceptance

- T-1 / AC-1 (FR-1–3): Add failing deterministic tests to `tests/runtime/customer/` for repeated consumer cancellation, cancel/response/pool cleanup ordering, lease release and timeout/late-result behavior. Use synthetic configuration and local SQLite/HTTP only.
- T-2 / AC-2 (FR-1–4): Implement private helpers and integrate dispatcher, client and lease. Re-run affected tests and the business real loopback HTTP cancellation test using SDK source.
- T-3 / AC-3: Run customer/stream/Harness release-gate regression, repository unit tests and original pre-commit hooks. Existing gate discovers `tests/runtime/customer/`; no separate optional gate. Verify paired languages, absolute links and whitespace.
- T-4 / AC-4: Record actual results tied to parent/diff, commit/push SDK independent user branch; rebuild business wheel and validate adoption as the next business milestone.

Verification uses `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py` and `.codex/run_native_precommit.py` with isolated synthetic configuration. Business integration uses `/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/mr-20261019/.codex/run_harness_backend_tests.py test_customer_mcp`.

## Review and delivery

Direct design review (review-spec skill unavailable): requirements, ownership, cancellation/error handling, compatibility, security, bounded waits, tests and bilingual equivalence reviewed. Resolved blocker: shield alone is insufficient; preserve generators in their original task and protect only cleanup leaf operations/joins. Existing user instruction to implement the blueprint authorizes this scoped repair; the user explicitly requires milestone commits/pushes to independent branches, with no merge/deployment.

Implementation/local verification: pass. Live Host/MCP/model, original customer 20 questions, PostgreSQL and remote CI: not_run; they are not established by this local regression.

Progress evidence: baseline 6 failed / 1 passed in 5.13 s; affected client/dispatcher/store regression 137 passed in 3.72 s; customer/stream/Harness gate regression 319 passed in 44.93 s. Business original MCP loopback HTTP suite 7 passed in 5.689 s. Direct trace confirms Host cancellation before client close with generator ownership unchanged. Original pre-commit five checks pass after formatting and relocating lease tests beside their fixture; 24 absolute document links valid. Full repository regression: 7,831 passed, 50 skipped, 4 xfailed, 6 subtests passed in 418.18 s, two workers; tested parent 9e14fe4b plus this change.
