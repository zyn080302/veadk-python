# Customer Shared HTTP channel client

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-channel/2026-10-20-customer-channel.zh.md)

Change ID: `customer-channel`; revision: 2026-10-20; status: implemented.
Component: [runtime-customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.md).

The approved Harness integration blueprint requires a public customer Runtime adapter. The current SDK dispatch supports `adk`, `codex`, `piagent`, and `dsh`; none implements the managed customer Shared channel. The ordinary Studio manifest has a different timeout default and drops `source`. Reusing it would change the catalog digest and violate the customer Host policy.

This milestone implements the independently usable HTTP client first. The remaining Runtime dispatch, ADK event mapping, persistent session mapping, business integration and live acceptance remain part of the original objective, not completed by this milestone. No server core is copied, no remote Agent becomes a tool, and no deployment or existing entry-point switch occurs.

## Requirements and scenarios

| Requirement | Scenario and required outcome |
| --- | --- |
| FR-1 | A caller submits a complete configuration and read-only skill snapshot: exact Shared fields/defaults/digest reach HTTP; ordinary Studio remains unchanged. |
| FR-2 | Capabilities, explicit session creation, run, result and cancel requests use one configured endpoint and session-owned client. Fresh response affinity replaces the previous value; it never becomes a business session identifier. |
| FR-3 | Given HTTP 200/ready/EOF without successful `run.completed`, the caller receives a fixed protocol failure. Wrong-run, malformed and oversized events fail closed. |
| FR-4 | Tool calls match run/scope/catalog/name/executor, are schema-checked and consumed once. Duplicate, stale and cancelled calls cannot be submitted again, including after ambiguous HTTP failure. |
| FR-5 | Each operation, entire run and cleanup are bounded. Cancellation/early iteration exit closes HTTP and sends at most one bounded `run.cancel`; the next run can start. No automatic run/result/session replay. |
| FR-6 | Secrets stay in explicit local configuration and request headers/body. No response body, URL, config or affinity is placed in exceptions/logs/repr. Redirects and environment proxy credentials are disabled. Limits reject non-finite values. |

## Design and tasks

Use existing `httpx`, Pydantic and AnyIO. `veadk/runtime/customer/` owns protocol values and a client with one live run per session. The HTTP client, bounded SSE parser and tool correlation are distinct responsibilities. The client exposes validated events and explicit result submission; it never executes tool code. A later runtime layer owns executor tasks and trusted business authorization. Caller-supplied transport is for isolated tests; production transport does not retry requests. See the component contract for authoritative API/state defaults.

- T-1 → FR-1/FR-6: protocol models and redacted errors; reject mutable snapshots by deep copying at the run boundary.
- T-2 → FR-2/FR-3/FR-5: HTTP client and bounded SSE framing, success/EOF/error handling, context-owned cancellation and resource cleanup.
- T-3 → FR-4: correlate calls and results, enforce schema/deadline/duplicates without replaying side effects.
- T-4 → FR-1–FR-6: write failing contract tests first; add tests to the existing Harness release workflow and its regression. Update paired documents and source-bound evidence before stage commit.

Affected files: `veadk/runtime/customer/`, `tests/runtime/customer/`, `.github/workflows/harness-sidecar-release-gate.yaml`, `tests/test_harness_sidecar_release_gate.py`. No Agent, Studio UI, existing runtime, dependencies or default configuration changes.

## Acceptance and verification

AC-1/FR-1: exact wire fixture/digest/defaults, invalid catalogs and complete read-only skill snapshots. AC-2/FR-2: capabilities, explicit `sessionId`, per-session affinity updates and isolation. AC-3/FR-3: fragmented UTF-8/SSE, malformed/oversized/unknown/wrong-run events, error/cancelled/EOF. AC-4/FR-4: correlated calls/results, duplicate and late responses, ambiguous delivery, bounded pending calls. AC-5/FR-5/FR-6: operation/run timeout, caller cancellation, early stop, next run, no redirects/retries and redacted failures.

Targeted command: `python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py tests/runtime/customer tests/test_harness_sidecar_release_gate.py`. The local wrapper isolates HOME, dotenv, telemetry and external networking; CI uses equivalent synthetic configuration. Required final checks: relevant Harness App tests, full Python regression with two workers, original pre-commit, language/link/diff checks. Real customer E2E remains `not_run` until dispatch/business integration exists. CI configuration alone is not executed CI evidence.

## Review and delivery

2026-10-20 direct design review (`review-spec` unavailable): checked wire fields against the retained managed Host types/transport, tool source and read-only policies, terminal/cancel semantics, Python 3.10 compatibility, errors, resource ownership, bilingual equivalence and testability. No blocking design findings. User authorization is the prior instruction to implement the blueprint, continue optimization and push verified milestones; this is an implementation step within that approved scope, with no new deployment permission.

Risks: server-side model retry/quota control remains outside this client; cancellation delivery may fail after network loss, so stream closure is also required and no cancellation acknowledgement is fabricated. Local correlation is not a distributed lease. Session persistence and cross-process recovery remain subsequent runtime/business work. The endpoint/config/headers are server-owned inputs, never browser-selected. Exact host-version live compatibility remains unverified.

Verification completed 2026-10-20 (`f7cc528e` plus this change): the old SDK first failed at the missing public entry; two additional negative review tests failed before refinement. Targeted 62 passed (3.31 seconds, customer branch coverage 87%), including real loopback HTTP reverse-tool roundtrip. The retained Host SharedChannelRun separately validated the generated request: 1 passed (2.43 seconds), offline protocol compatibility only. Two-worker full regression: **7594 passed / 50 skipped / 4 xfailed, plus 6 subtests passed, 430.70 seconds**. All five original pre-commit hooks passed. Python 3.10 grammar, paired contract IDs, absolute links and diff checks passed.

AC-1–AC-5 and T-1–T-4 are complete for this client milestone. Real customer E2E, model/MCP, original20, new Linux artifact and remote CI remain `not_run`: Runtime/business bridging is not connected, so this milestone cannot stand in for their acceptance. Frontend and Codex/Pi smoke are `not_applicable` because those implementations are unchanged; existing Sidecar coverage thresholds are unchanged. The full regression does not validate the 50 skipped cases.

Review clarification: serialize control-operation ownership, and reject successful terminals after error events or with pending results. These enforce FR-2/FR-3 and do not expand scope. Negative tests precede the implementation refinement.

Source binding (tested files for this milestone):

| Path | SHA-256 |
| --- | --- |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.github/workflows/harness-sidecar-release-gate.yaml | e68432b4c3f78d76e0bc6cea7b10bcb5d7c97dcc3638d12617122215ceaee645 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/customer/test_channel.py | ad1ef25893754688bf64dcb3953af112e6e3bb1880a9082474f4e355244e06d2 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/test_harness_sidecar_release_gate.py | f9847f48bf94895db551c76b4c3a4d7a89109434d201f7fbcf124b8c7c71d1d1 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/__init__.py | 589bd25a1a6cf94f7eb6dd4781946a1e2b6ff5a303f391a35473a2643813b299 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/client.py | 05aa0a4211b172b83f3c1cedfcc148e33f578bcc4f0cdaa8b7d69fa2dc219b63 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/protocol.py | c0ddee4e633234d0ae6708cc48378fde5ffc3a757f94f7f07090fe0ac192f1a0 |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/sse.py | 8d85d7f44df50358afd663c62b9bbdaafacc229776bd68b83994eb8ce68f8bc4 |
