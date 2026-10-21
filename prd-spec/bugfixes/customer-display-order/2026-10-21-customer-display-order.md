# Customer display publication order

[中文版](2026-10-21-customer-display-order.zh.md)

Change ID: customer-display-order. Created/revised: 2026-10-21. Status: approved.

## Evidence and scope

SkyEyes Devbox comparison `2346323d4bf670f7`, SDK `0bf87db3`, failed at the second baseline turn with `display_conflict`. The completed journal and ADK display each contain seven events, no duplicate IDs, and identical content by ID, but different order. This proves an ordering conflict, not its generating mechanism. The full baseline/Jev comparison and answer quality remain incomplete.

`CustomerRuntime._saved_prefix` correctly requires identical ordered contents. `DatabaseSessionService` reads by timestamp then ID. Native tool call events are constructed before execution but published with their response after execution. Projected Host events can be emitted during that wait; final answers are constructed before final publication as well. Creation time is therefore not necessarily publication order. A real SQLite/ADK regression must establish this mechanism before implementation; do not attribute the live failure to timestamp precision without evidence.

Goal: newly published customer events preserve their journal order on database readback, so a completed turn can continue or recover without re-executing tools. Non-goals: changing ADK storage schema, weakening content/prefix checks, repairing existing conflicted histories, replaying tools, changing MCP schemas, production release, or claiming performance/quality success.

## Requirements and design

- FR-1: Given interleaved Host display and a pending native tool, when the completed stream is persisted and read through real `DatabaseSessionService`, its durable event order must equal publication/journal order; a second turn must succeed.
- FR-2: Assign local display timestamps once, immediately before durable journal append and yield. Use current local time, strictly after prior persisted display timestamps at ADK database microsecond resolution, including frozen/backward clock cases. This field describes local publication, not tool execution duration. Partial events remain transient. Never modify IDs, content, actions, usage, or an already journaled event.
- FR-3: Keep ordered full-payload verification, duplicate/content/gap rejection, lease ownership, terminal/ACK/cleanup and cancellation behavior unchanged. Recovery appends only an actual missing suffix, uses recorded timestamps, and contacts neither Host nor tools. Existing reordered histories remain conflicted.
- FR-4: Verify new events after service restart and partial suffix recovery, as well as the original Devbox five-turn two-arm comparison with a fixed new wheel. Full answer quality and net performance are evaluated independently of this correctness fix.

Owner: [runtime-customer](../../../specs/runtime-customer/README.md), CON-4/CON-5. Projection and native-tool producers keep their existing interfaces; Runtime is the only point that owns both journal and yielded events. Avoid separate clocks in each producer, sorting histories after persistence, or accepting an unordered set as a saved prefix. No dependency, configuration, authentication, permission, public signature, or schema change. Storage should preserve microsecond ordering; other timestamp resolutions require their own verification. Clock correction must be local and constant-space, with no waiting or network calls.

## Tasks and acceptance

| Requirement | Task | Acceptance | Verification |
|---|---|---|---|
| FR-1 | T-1: real database interleaving regression before production edit | AC-1: old code fails with reordered same-content events; corrected code continues | `uv run --extra dev pytest tests/runtime/customer/test_display_order.py` |
| FR-2/FR-3 | T-2: assign publication time in `runtime.py` | AC-2: equal/backward clock and restart pass; full payload and negative checks remain enforced | Same targeted tests plus `tests/runtime/customer/test_runtime.py` |
| FR-3/FR-4 | T-3: consumer gates, review and bilingual reconciliation | AC-3: customer/Harness gates, full SDK regression, pre-commit pass | `uv run --extra dev pytest tests/runtime/customer tests/test_harness_sidecar_release_gate.py`; `uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"`; `uv run --extra dev pre-commit run --all-files` |
| FR-4 | T-4: fixed wheel and business verification | AC-4: installed Runtime gate and Devbox five-turn pair rerun, original failures retained | SkyEyes `scripts/check.py --scope native-runtime --sdk-installed` with existing pinned source paths; `scripts/devbox_customer_live_pair.py --dependency-base <verified-sdk> --case ambiguous --confirm-followup --followup-neighbors` |

The existing mandatory Harness release workflow includes all `tests/runtime/customer`, so the regression is automatically required. Offline tests use synthetic data, real local databases and a mock Host; no external models or credentials. Devbox validation uses the existing authorized isolated wrapper and is separate from offline evidence.

## Review and delivery

Direct design review (`review-spec` unavailable): scope and owner are bounded, no content-check bypass or automatic replay, public interfaces unchanged, real storage covers the missing layer. English/Chinese requirements and identifiers reviewed together. The user's active goal authorizes SDK/Runtime corrections and Devbox iteration; this is routine implementation within that scope, not a separately claimed design or release approval. T-1 establishes the ordering mechanism first; if evidence contradicts it, revise the design before T-2.

Targeted customer/release contracts: `pass` (357 tests, 30.04 s; wall time 31.603 s), including eight new regressions. Five pre-commit hooks and bilingual identifier/link checks: `pass`. Full regression: `pass` (7917 passed, 50 skipped, 4 xfailed, 6 subtests passed; 424.04 s, wall time 425.315 s; 2 workers). Skips do not prove the corresponding capability. Its first invocation failed before collection because an unavailable external subtests plugin was explicitly loaded; pytest 9 already provides subtests, so the corrected command omits that plugin. The failed startup record is retained and is not counted as a product regression. No correctness, artifact, deployed recovery or performance success claimed. Remaining risks: old conflicted sessions still require explicit reconciliation; coarse timestamp stores outside tested ADK/SQLite are unverified; a wall clock discontinuity across separate invocations may also affect ADK's user/workflow events, which this Runtime does not own.

T-1 evidence: old SDK regression fails (1 failed, 15.58 s) after real database reopen: complete payloads match by ID, ordered IDs do not. Interleaving creation/publication is now a reproduced cause of this failure class. The exact old live event schedule is not reconstructed. Proceed with T-2; original full-content check remains unchanged.

Business source-mode integration: `pass`, 11 checks plus real process restart, identity/history preservation and no paid query replay. It imports this source diff; not an installed-wheel or live-provider acceptance. T-1/T-2/T-3 and AC-1/AC-2/AC-3 are complete; fixed-wheel and Devbox T-4/AC-4 remain pending. Verification binds `0bf87db3` plus this diff: {"veadk/runtime/customer/runtime.py": "8b257bf0e3e8867dcfa858b3436195804586b2ed937653587938f6cf313a9ec1", "tests/runtime/customer/test_display_order.py": "cdfa614cdc65bc85b7caac27d7c375e28ef3e233e2f251c2fefce1e2bab0c4d1"}.
