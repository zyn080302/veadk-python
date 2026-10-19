# Customer Runtime integration

[中文](2026-10-20-customer-runtime.zh.md)

Change ID: runtime-customer. Created/revised: 2026-10-20. Status: implemented.

## Background, goal and scope

The public Agent runtime selector cannot reach the existing customer client, dispatcher, ADK projector and durable store. Agent initialization resolves local credentials and constructs a model before dispatch. Standard Harness clones can switch runtime and model. This stage connects those existing components through a real registered Runtime and a server-constructed Agent served by HarnessApp. It does not complete the SkyEyes migration.

Non-goals: native Agent.tools/callback state bridging, configuration from request JSON/environment, Host model budgets/retries, authentication, production database integration, wheel/image/deployment, UI changes or customer evaluation. Unsupported configuration must fail before remote execution. Later P0–P4 work retains these obligations.

## Requirements and design

- FR-1: Register CustomerRuntime and CustomerRuntimeConfig; Agent(runtime="customer", customer_runtime_config=...) branches before local key lookup, tool preparation, model creation or config logging. Config is a server-owned object excluded from Agent serialization/repr; clone retains it. Unsupported ADK model/tool/callback/state options fail explicitly.
- FR-2: Bind local identity to endpoint, configuration, catalog and engine revision through the durable store. Before a first remote run reserve the invocation. GET the exact remote session, create only before any earlier turn; never recreate missing history. Do not list sessions. Restore private affinity before HTTP and persist every new affinity before allowing further requests.
- FR-3: Send only the current nonempty text input. Full Host agent configuration/environment, declarative tools/readonly skills and async executors come from the server config. Use existing dispatch/projector cleanup and no whole-turn retries. A total run deadline includes preparation and execution; cleanup and database release are bounded separately and covered by the lease.
- FR-4: Journal full local events before yielding; mark completed only after verified terminal, tool ACK and cleanup. ADK may save on a different task after Runtime finishes: leave completed pending, verify journal contents in ADK storage at the next invocation before acknowledging. Missing display blocks execution. Provide explicit display recovery that appends only a missing suffix, verifies persistence and never uses HTTP/executors. Reject conflicting or reordered history. Uncertain execution/expired owners are not replayed or taken over.
- FR-5: Standard HarnessApp serves a prebuilt customer Agent. Customer overrides are limited to an unchanged runtime; other overrides or switching to/from customer fail. HarnessConfig environment construction remains adk/codex until a server config factory exists. Direct Agent mutation/clone cannot switch a bound customer Agent into a local model. Explicit max_llm_calls is rejected because this Host contract does not enforce it; default ADK value is not a Host guarantee.

## Tasks, tests and acceptance

| Requirement | Task | Acceptance | Verification |
| --- | --- | --- | --- |
| FR-1 | T-1 public config/dispatch/gates | AC-1 no local model/key creation; clone/serialization safe | negative initialization and mutation tests |
| FR-2 | T-2 client restore and session lookup; lease history query | AC-2 exact binding, restart, affinity ordering and missing history fail closed | client + actual Runtime tests |
| FR-3 | T-3 compose existing components | AC-3 text/tool roundtrip, continuation, cancellation, timeout, error do not replay | real Agent/Runner and Harness HTTP with synthetic Host |
| FR-4 | T-4 journal and explicit recovery | AC-4 actual ADK save failure recovers display with no second tool execution | failing SessionService + SQLite restart |
| FR-5 | T-5 Harness guard, gate and docs | AC-5 request cannot change engine/model/config | Harness /run and /run_sse tests |

Affected files: veadk/agent.py, veadk/runtime/__init__.py, compat.py, customer/{config,runtime,client,session_store,__init__}.py, veadk/cloud/harness_app/{types,utils}.py, tests/runtime/customer/, Harness workflow gate. No dependency, frontend or generated artifact changes. Component contract: runtime-customer; additive client/store methods update their existing paired specs.

Required checks: isolated targeted customer/runtime/Harness tests; Python regression with two workers excluding explicit Codex/Pi smoke; original pre-commit; bilingual contract/link checks. Real Host/model/MCP and PostgreSQL are not_run, not simulated into a live acceptance.

## Review and authorization

Direct review performed because review-spec is unavailable. Reviewed component reuse, strict unsupported configuration, affinity persistence ordering, ADK asynchronous persistence, cancellation, duplicate execution, engine binding, compatibility and bilingual equivalence. Resolved: do not acknowledge merely on generator resumption; inspect actual ADK storage. Do not copy remote actions or use Agent.tools until the callback bridge exists. Existing user instructions to execute the integration blueprint and continue optimization authorize this stage; the latest instruction explicitly authorizes milestone commits/pushes to independent branches. No new deployment authorization.

Before implementation, the public import failed test collection (1 ImportError), establishing the missing entry point. Risks: Host configuration/schema still server-owned; this module does not authenticate local user IDs or redact tool response bodies; noncooperative tools require external isolation. Crash-held leases need explicit later recovery rather than takeover.

Review extension before implementation: standard ADK HTTP sets custom_metadata=None and Harness installs its local call-limit plugin even without a limit. Accept only the empty metadata default, and skip that no-op plugin for a customer Agent; reject an actual App call limit. Harness app.py joins affected files. Native ADK workflow clone fields (chat mode, null parent, boolean rerun_on_resume/wait_for_output) are compatible; durable reservation still prevents rerunning a turn.

Additional source review before changing continuation: preserved Host shared_server.py and studio_session.py both reject a missing Session before reasoning. Therefore only the first turn performs exact-session GET/create; continuation restores affinity and submits to that session-required protocol directly. This avoids downloading an ever-growing reasoning history just to check existence. HTTP rejection still blocks the reserved turn; no automatic Session recreation.

## Delivery evidence — 2026-10-20

Scope: parent ba8f29de0db750d222b8061cc1fb6efb6ff05426 plus this commit's customer Runtime, client/store hooks, Agent/Harness integration, gates and paired contracts. All FR-1–FR-5 / T-1–T-5 / AC-1–AC-5 are implemented and covered by tests/runtime/customer/test_runtime.py. Final review reconciled public interfaces, callback rejection, bounds, failure/recovery ordering and both languages; no blocking findings remain in this stage.

| Check | Actual result |
| --- | --- |
| python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py tests/runtime/customer/test_runtime.py | pass: 39 tests, 7.93 seconds |
| Customer, stream lifecycle, Harness call-limit and release gate tests | pass: 286 tests, 31.18 seconds, before the last five additional Runtime cases; final full regression includes them |
| python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke' | pass: 7803 passed, 50 skipped, 4 xfailed, 6 subtests passed; 407.35 seconds, 2 workers |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.venv/bin/pre-commit run --all-files | pass: all five original hooks, using isolated HOME and existing local caches |
| Python 3.10 AST, bilingual IDs, absolute document links, git diff --check | pass |
| Real loopback Harness HTTP → customer HTTP → executor/result → actual ADK persistence/read-back | pass: two turns; synthetic Host/configuration/data, no cloud call |
| Actual ADK final display save failure and recover_display | pass: missing display recovered without HTTP or duplicate tool execution, then continuation succeeds |
| Live Host/model/MCP, production PostgreSQL, original customer 20 questions, remote CI, wheel/image/deployment | not_run: separate remaining integration and acceptance work |

Skipped tests are not acceptance evidence. The isolated test wrapper blocks non-loopback Python network and does not load user credentials. No production performance improvement is claimed. Google ADK Runner and Harness HTTP are verified; VeADK Runner.run() still supplies max_llm_calls=100, rejected by customer until Host budget/caller adaptation. Business tool callbacks, authentication, production storage and P0–P4 remain open.
