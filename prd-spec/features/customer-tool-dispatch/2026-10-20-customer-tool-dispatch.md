# Customer reverse tool dispatch

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-tool-dispatch/2026-10-20-customer-tool-dispatch.zh.md)

Change ID: `customer-tool-dispatch`; created/revised: 2026-10-20; status: implemented.
Component: [runtime-customer-tool-dispatch](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-tool-dispatch/README.md).
Predecessor: [customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-channel/2026-10-20-customer-channel.md).

## Evidence and scope

The public Shared client validates calls but deliberately does not execute them. Awaiting a tool inline in the SSE reader would prevent receiving `tool.cancel` while the tool runs. Unbounded task creation would move customer load into the business process. Pi's ADK tool bridge exposes async executors with `(arguments, call_id)`, which can be reused later without moving the model loop into the business agent.

This stage adds a complete, independently usable dispatcher over that client. It does not claim `Agent(runtime="customer")`, ADK event conversion, durable session ownership, trusted business identity, shared quotas, or business deployment. Those remain required stages of the approved integration blueprint. No model, credential, configuration, or Runtime access is needed for offline verification.

## Requirements and scenarios

| Requirement | Observable behavior |
| --- | --- |
| FR-1 | Given an explicit immutable request and matching async executors, enter a dispatcher context and consume validated Shared events; missing/extra/synchronous executors fail before HTTP. |
| FR-2 | Given concurrent tool calls, execute at most 8 by default (configurable 1–64); the client retains its 64 pending/1024 per-turn bounds. Queue time counts against each tool deadline. |
| FR-3 | While a tool runs, continue reading SSE. On tool.cancel or context exit, invalidate its result before cancelling its task. A tool suppressing cancellation cannot submit a late result. |
| FR-4 | Tool exceptions produce fixed error results without exception text. Tool deadline expiry aborts the run; do not submit after expiry or retry tools/results/runs. Unexpected executor cancellation aborts the run. |
| FR-5 | Bound event buffering (default 16, configurable 1–256); if the consumer cannot keep up, fail with `event_backpressure`, cancel the run and release cooperative tasks. Event forwarding is observation only. |
| FR-6 | Publish success terminal only after all still-required tool submissions have completed successfully; explicit tool.cancel no longer requires a result. A failed/ambiguous result acknowledgement overrides an early Host success; no final success on failure. |
| FR-7 | A single context owns one reader, bounded tool tasks and one client run. Close cancels once and waits at most 10 seconds by default for the owner plus child cleanup. `quiescent` reports whether all tasks stopped. A non-cooperative executor triggers `cleanup_timeout`; callers must quarantine the dispatcher/client and must not reuse execution context until quiescent. Python cannot forcibly stop such code. |

## Design and files

Add `veadk/runtime/customer/dispatch.py`, export `CustomerToolDispatcher`, add `tests/runtime/customer/test_dispatch.py`. The existing Harness release gate already runs this directory. No changes to dependency metadata, Studio, or existing runtime dispatch are needed.

The context owns the background pump; consumers use `events()` once. Reader and executor tasks inherit the caller's current context at creation, but this is not an identity protocol. The future business adapter must bind a revocable trusted run context and a session lease. A semaphore controls execution; a bounded queue carries observed events. Fixed error codes are the only diagnostics. The dispatcher never chooses endpoints, headers, identities, tool catalogs or Skills.

The pump prioritizes task failures over buffered events. It reserves terminal forwarding until child submissions finish. On cleanup, authorization to submit is revoked before cancellation. Completed task exceptions are always retrieved, including tasks that finish after a cleanup timeout. Use cooperative async executors; blocking/synchronous tools require an explicitly bounded business worker service in a later stage.

## Tasks and acceptance

| Requirement | Task | Acceptance | Verification | Status |
| --- | --- | --- | --- | --- |
| FR-1–FR-2 | T-1 API and scheduling | AC-1 preflight and concurrency cap | targeted dispatcher tests | pass |
| FR-3–FR-4 | T-2 cancellation and failure | AC-2 no late/duplicate HTTP submission; fixed errors | cancellation, queue deadline and exception tests | pass |
| FR-5–FR-7 | T-3 lifetime and backpressure | AC-3 bounded buffers/cleanup, truthful terminal, next invocation | slow consumer, ACK race, cleanup and reuse tests | pass |
| FR-1–FR-7 | T-4 reconcile and deliver | AC-4 existing client, real loopback reverse HTTP, full SDK regression and original hooks | commands below | pass |

Commands: `python3 .codex/run_offline_tests.py tests/runtime/customer`; full SDK: `python3 .codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`; original pre-commit hooks in an isolated HOME/cache. `.codex` wrappers are local evidence infrastructure; CI uses `python -m pytest -q tests/runtime/customer` in the existing Harness gate.

## Review, authorization and risks

Direct review completed before production/tests (review-spec skill unavailable): protocol remains owned by customer-channel; no new model loop, ambient auth, persistence writes or retries; semaphore and queue have hard limits; cancellation invalidates before joining; remote success waits for local ACKs. Both language versions have matching identifiers, limits and acceptance. Existing user instruction to implement the integration blueprint and push verified stages authorizes this stage; no new deployment or merge is authorized.

Unverified risks: actual Host event timing, tool cancellation cooperation, workload-appropriate concurrency and event capacity, durable lease recovery and real business identity. Defaults are safety bounds, not customer capacity claims. Integration and real customer 20-question acceptance remain open. Do not mark the overall blueprint complete from this milestone.

Review correction before delivery: a failing regression measured 0.3047 s cleanup with a 0.2 s budget because internal failure and context exit each restarted waiting. Both now use one monotonic cleanup deadline, including repeated close. This strengthens FR-7 without changing scope.

## Final verification record

2026-10-20, SDK b4d91382 plus this change. The missing public API failed first; the additional stacked-cleanup regression also failed before the fix. Final customer targeted checks: 92 passed (3.60 s); combined statement/branch coverage is 94% for dispatch and 89% for all customer modules. Real loopback HTTP covers both direct client and dispatcher reverse tool delivery.

Final-source SDK regression: 7625 passed / 50 skipped / 4 xfailed / 6 subtests passed (388.29 s, 2 workers). All five original pre-commit hooks passed; Python 3.10 grammar, bilingual IDs/links and diff checks passed. An earlier regression was interrupted after the cleanup revision and is excluded from final evidence. Real Runtime, model/MCP, customer 20 questions, remote CI and new business image are not run; deployment is outside this milestone.
