# Durable customer session ownership

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/runtime-customer-session-store/2026-10-20-customer-session-store.zh.md)

Change ID: runtime-customer-session-store. Created/revised: 2026-10-20. Status: implemented.

## Evidence and scope

The existing customer client, dispatcher and event projector require caller-owned durable exclusion. Process locks disappear on restart, allowing a turn with completed tool side effects to be submitted again. This stage provides the persistence needed by the formal Runtime, using the existing SQLAlchemy AsyncEngine dependency. Runtime registration, affinity restoration in the HTTP client, callback bridging and business wiring remain subsequent blueprint tasks; this stage does not complete migration.

## Requirements and design

| Requirement | Task | Acceptance |
|---|---|---|
| FR-1: stable identity and engine binding | T-1: store and public exports | AC-1: independent connections produce one owner; user/engine isolation |
| FR-2: reserve invocation before remote submission | T-2: claim/begin/release | AC-2: duplicate IDs, expired owners and uncertain runs cannot replay |
| FR-3: durable, bounded local display journal | T-3: append/complete/read/ack | AC-3: reopen DB and recover display without executing tools |
| FR-4: fixed errors and private affinity | T-4: contracts, regressions, gates | AC-4: no identity, SQL parameters or affinity in diagnostics |

Use three private tables, separate from ADK Session.state. Short transactions use versioned conditional updates rather than long-held transactions. Initialize schema explicitly. Require a caller-owned AsyncEngine with SQL echo disabled and parameters hidden; the caller owns DB deadlines, pools, encryption and disposal. This adds no dependency, network call, credential loading or telemetry.

The state sequence is idle → running → completed → idle. Claim has a finite deadline. No automatic expiry takeover: running, blocked or expired unreleased ownership requires recovery. Release during running blocks future execution. Completed turns remain display-recoverable after release/restart. The caller explicitly acknowledges verified ADK persistence before another turn. Invoke begin_turn before any remote submission; duplicates never resubmit. Journal only trusted projected complete Events, bounded by count and bytes; completion requires an explicit final text Event and caller-confirmed remote success, tool ACKs and cleanup.

The maintained contract is [runtime-customer-session-store](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-session-store/README.md). Affected files: /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/session_store.py, /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runtime/customer/__init__.py, customer tests and Harness release gate. No frontend, dependency, CLI or deployment change.

## Tests, risks and review

Write failing tests first. Use temporary SQLite files and independent AsyncEngines for races, restart, cancellation, expiry, duplicates, limits and sanitized errors. Run `python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/customer`, broader SDK tests and existing pre-commit. Production PostgreSQL, public Runtime HTTP and customer 20 questions remain not_run; dialect compilation is not live acceptance.

The layer does not authenticate supplied identity, filter content secrets, stop uncooperative tools or promise distributed exactly-once. Uncertain side effects remain blocked. No force unlock, background renewal or automatic retention deletion. Business retention and a dedicated recovery procedure remain caller responsibilities.

review-spec unavailable: directly reviewed interfaces, state transitions, concurrency, cancellation, error boundaries, security and bilingual equivalence. Rejected automatic expired takeover and execution before display acknowledgement. Proceed under the user's existing blueprint implementation and milestone commit/push authorization; no merge/deployment authority. Design review passed before code/tests. Verification results are recorded below.

Review refinement before implementation: keep events in separate rows with per-turn counters; avoid rewriting the complete journal on every append.

## Verification record (2026-10-20)

Based on SDK `5c95434465f8acb2373b46fbefbecc7196124f0f`; all T-1–T-4 and AC-1–AC-4 for this persistence stage are implemented. The failing baseline was one collection error because CustomerSessionStore was not exported. The final component adds 37 tests. Customer/lifecycle/gate suite: 232 passed in 23.37 seconds. Full SDK: 7764 passed, 50 skipped, 4 xfailed, 6 subtests passed in 399.99 seconds, two workers, explicit Codex/Pi smoke excluded. Five existing pre-commit checks, staged secret scan, Python 3.10 syntax, paired identifiers and eight absolute links passed. An earlier stalled coverage invocation was stopped; no coverage result is claimed.

Full command: `python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`. Tests use temporary HOME/SQLite and blocked external networking. The tool roundtrip combines the actual client/dispatcher/projector over MockTransport; withholding display acknowledgement models a failed local save. It is not a public Runtime, actual ADK persistence failure, production PostgreSQL or live customer acceptance test. Source digests and final commit binding: [evidence](/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/mr-20261019/docs/project/evidence/customer-session-store-verification.json). No deployment or main/master merge.
