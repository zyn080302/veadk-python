# Apply the Harness call limit to delegated HTTP runs

[中文](2026-10-20-delegated-run-limit.zh.md)

Change ID: harness-http-call-limit. Created/revised: 2026-10-20. Status: implemented.
Component: [harness-service CON-4](../../../specs/harness-service/README.md).
Predecessor: [service embedding](../../features/harness-service-integration/2026-10-20-public-app-and-session.md).

## Background, goals and scope

HarnessApp stores `max_llm_calls`, and its default factory reads `MAX_LLM_CALLS` (default 10). The delegated ADK `/run_sse` handler creates RunConfig without this value; `/run` also omits it. A multi-step query can therefore exceed the configured per-invocation limit. Source evidence: `HarnessApp._mount_run_sse_override`, ADK `ApiServer.get_fast_api_app` and `InvocationContext.increment_llm_call_count`. HTTP reproduction is pending before implementation.

Restore that existing configuration on delegated `/run` and `/run_sse`. This is a per-invocation model-call bound, not TPM/RPM admission, transport retry accounting, a tenant security boundary, or a performance measurement. A2A, live audio, provider integration, and changing the default business entry point are outside this repair; full-chain protection remains subsequent work. Existing explicit Harness override precedence stays unchanged.

## Requirements and scenarios

- FR-1: Given an app limit of 1 and a query needing a model/tool/model sequence, either delegated route invokes the model once, preserves the completed tool event and reports the original execution error before a second model call.
- FR-2: With limit 2, the same sequence completes. `None` preserves ADK defaults; nonpositive values retain RunConfig's existing unlimited semantics. Each invocation has its own counter, including concurrent sessions and later turns.
- FR-3: Missing sessions still fail with HTTP 404 before model execution. Metadata, state deltas, invocation IDs, artifact event shaping and disconnect cancellation remain owned by ADK. Explicit `/run_sse` Harness overrides continue to take precedence on their existing route.
- FR-4: Closing a client request cancels an in-progress model generator and releases its resources. A following request succeeds. No provider, credential, filesystem or background task is added by the fix.

## Design and contract impact

Add a private stateless BasePlugin that copies the invocation's RunConfig and changes only `max_llm_calls` in `before_run_callback`. ADK continues to count and enforce model calls. Register it once per ADK-managed Runner through the public `AdkWebServer.get_runner_async` override and `PluginManager.get_plugin/register_plugin` APIs. The server holds a reference to the enclosing HarnessApp so the plugin reads the same current configured value; `None` leaves the invocation unchanged. Do not modify request objects, shared RunConfig instances, Runner.run_async, or global ADK classes. Registration after awaited runner lookup has no suspension point, so concurrent lookups cannot double-register on a shared runner.

Keep the captured ADK handlers and their session validation, event serialization and cancellation ownership. Avoid redirecting all limited requests into `_run_sse_events`: that route auto-creates sessions and would change the 404 contract. Avoid copying upstream route implementations or monkeypatching RunConfig globally. The plugin is separate from optional Harness enhancement plugins and does not force the override route. It is not attached to per-request override runners or the A2A runner.

Update CON-4 in both component languages. No new public arguments, request fields, storage format or dependency is needed. This patch does not authenticate user IDs or authorize clients to change limits. Errors retain existing route behavior: SSE error event; `/run` server error. The limit is an app default, not a new hard tenant ceiling.

## Tasks, verification and acceptance

| Requirement | Task | Acceptance | Verification | Result |
| --- | --- | --- | --- | --- |
| FR-1/2 | T-1: HTTP regressions before code; T-2: plugin/server integration in `veadk/cloud/harness_app/app.py` | AC-1: actual fake-model/tool counts and terminal outcome match limits on both routes | `tests/cloud/test_harness_app_call_limit.py` | pass |
| FR-3 | T-3: compatibility and concurrent-turn cases | AC-2: 404, metadata/state, explicit overrides and independent counters remain correct | New and existing Harness HTTP/contract tests | pass |
| FR-4 | T-4: real loopback HTTP disconnect cases | AC-3: model cleanup and successful next request | New test file, bounded local uvicorn server | pass |
| All | T-5: add regression file to required Harness release gate; review paired docs and push validated branch | AC-4: targeted and broad regressions, pre-commit, clean diff and secret scan | Commands below | pass |

Run the repository Python environment with synthetic configuration, temporary HOME, disabled dotenv/telemetry and external network denied. Targeted: `python3 .codex/run_offline_tests.py tests/cloud/test_harness_app_call_limit.py tests/cloud/test_harness_app_http.py tests/cloud/test_harness_app_contract.py tests/cloud/test_harness_app_embedding.py tests/test_harness_sidecar_release_gate.py`. Broad regression: same wrapper with `-p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`. The wrapper is local isolation tooling; CI uses `python -m pytest` with synthetic settings. Before commit synchronize intended base, then run `pre-commit run --all-files` in the isolated environment with existing local cache. Do not claim remote CI or provider E2E from these tests.

## Risks, review and delivery

Upstream plugin/Runner behavior is covered by HTTP execution rather than only mocks. Preserve the original error representation; do not hide it as a successful final answer. A limit can intentionally leave a completed tool step without a final model synthesis. Completed session events remain readable; a new invocation receives a fresh budget. This repair does not bound total wall time or cross-replica quota use.

2026-10-20 design review: requirements, public extension points, concurrency, cancellation, security, route compatibility and bilingual equivalence reviewed directly; `review-spec` is unavailable. No unresolved design blocker. Authorization comes from the user's existing instruction to complete the integration/performance blueprint and push validated milestones to independent branches; no new merge/deployment permission is inferred. At this design checkpoint, implementation and all checks were pending. Scope changes require updating this pair before code changes.

Verification checkpoint (2026-10-20): before production edits, the new HTTP test file against `d20cc73d935ba93800c74734e9c7bffe8aeaf8b5` produced **3 failed / 17 passed in 38.04s**. Both delegated routes called the synthetic model twice at limit 1; the default run after an explicit override also exceeded the limit. After the repair, the targeted command above produced **113 passed in 32.83s**, including real loopback HTTP cancellation before/after output and another successful turn. This is synthetic integration evidence, not provider or customer validation. Fetched/rebased `origin/main` remained `402a3da9cc1a9b4201411d660b51dd6bf023f06a`; all original pre-commit hooks passed. Broad regression passed: **7533 passed / 50 skipped / 4 xfailed**, plus 6 subtests passed, in **413.47s** with two workers. Skips and expected failures are not counted as passes. AC-1 through AC-4 are satisfied for this SDK repair; the customer integration plan remains incomplete. Production source SHA-256: `veadk/cloud/harness_app/app.py` = `9bc5087225ebfc85b11f07c319d601d85b1bc947069f8b32a83d9c9fc26e6b65`; new test SHA-256 = `f9ff9f4e0c7fae1dc49c26bb4ea67b39410fa53899c5b197c5da0504f770c209`. Remote CI, business artifact update and release have not run.
