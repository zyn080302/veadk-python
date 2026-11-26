# Bounded Codex input with retrievable context

[中文版](2026-11-26-context-reader.zh.md)

Status: implementation and offline source verification passed; final image/customer acceptance tracked separately. Date: 2026-11-26.

## Evidence and scope
Codex rejects aggregate TextInput beyond 1,048,576 Unicode characters before model execution. Tool continuation following an instruction-hash mismatch rebuilds the thread with full history. Original logs confirm this rejection boundary; the exact changing instruction and full original input are unavailable. Existing thinking classification repair remains the base. User explicitly requested this SDK repair after diagnosis; this is scope approval, not customer deployment approval.

## Requirements and design
FR-1: Preserve normal inputs and all knowledge-base choices. Do not disable instruction-change checks, truncate facts silently, replay tools or increase model/output/time budgets.
FR-2: Before RPC, cap text including the shim marker. For oversized replay or resumed backfill, keep the current request and recent exact excerpts, and retain the complete original text in invocation-local memory. Expose a read-only `_veadk_read_context` tool with bounded paging and literal search. It performs no shell, disk or network access. Every reference is valid only for this invocation and cannot access another invocation's input.
FR-3: Use existing ADK tool dispatch, callbacks, tool-count and timeout limits. Do not expose internal context reads as new historical evidence on replay. Sources remain data, not privileged instructions. Current request larger than the RPC budget is also referenced without losing its original text. Unknown references and invalid bounds return explicit errors; cancellation closes the original tool registration. There is no retry or new model phase.
FR-4: Normal text at or below the RPC limit remains exact; reserve the actual marker before packing. Overflow replacement has a bounded current-request excerpt, full source reference, and beginning/recent excerpts. Latest references are supplied to resumed turns even when the full-history input is not selected. References are explicitly turn-local, not persistent citations.

## Alternatives and risks
Raising max_tokens, splitting TextInput, dropping knowledge bases or truncating history cannot preserve this contract. A shell-backed file would fail for shell-disabled agents. Paging may add existing tool calls and requires model selection; therefore offline deterministic mechanism verification is separate from real-model quality and customer online acceptance. No changes to Codex binary, Host, third-party dependencies or stored sessions.

## Tasks and acceptance
T-1/AC-1: Same entrypoint regression fails on the base due to oversized text; passes after repair, including stable current question and source recovery.
T-2/AC-2: Boundary, Unicode, current-only oversize, backfill, isolation, invalid arguments, expired references, callbacks, cancellation and history filtering tests. Reconstruct exact source by paging; recover a fact in the middle, not only a prefix.
T-3/AC-3: Real Codex process, scripted loopback provider: first/follow-up/instruction change, MCP read, final reply/history, failure/recovery. Existing mandatory unit-tests and serial smoke discovery include new cases. Synthetic provider is not customer model acceptance.
T-4/AC-4: Affected/full required repository gates, independently installed successor wheel, exact source/metadata binding and deployment contract update. Existing wheel remains immutable. Cloud image and customer online acceptance recorded separately.

## Review
Manual design review (review-spec unavailable): reviewed isolation, bounded outputs, actual RPC marker accounting, no external effects, callback policy, finite existing budgets, replay semantics and bilingual parity. User's current repair instruction provides scope authorization; no repeated permission request. Component contract: [codex-input-context](../../../specs/codex-input-context/README.md).

## Verification
2026-11-26: 25/25 context checks passed. The same real Codex 0.162.1 direct/shim test with SQLite history, fresh Runner instances and failure recovery fails on the baseline with -32602/1048576 and passes 2/2 on the candidate. The provider is a local script, not a customer model.

The independently installed successor wheel `1.1.15.dev15+aiopsharness.20261126.inputfix1` passes 46/46 context and thinking-classification checks. It derives from the immutable thoughtfix1 wheel, changes three SDK files and adds input_context.py; 1007 existing payloads and dependency metadata remain unchanged. RECORD and installed source binding pass. Build entrypoint: `scripts/build_codex_input_context_wheel.py`.

The repository pins Codex 0.159.2; the customer image pins 0.162.1. Neither dependency is changed. Repository gates and customer integration use their respective original environments. Earlier two pin-test failures came from using the customer version for repository metadata checks; test-driver Path, stream and retry-count errors are retained separately and are not defect witnesses. The parallel regression passed 7185 cases with 54 explicit skips; skipped external-service, platform and unsupported-capability cases are not counted as passes. Pre-commit passed all five checks. After preparing isolated MySQL 8.0.46 and PostgreSQL 17 services, the original serial Codex smoke selection passed 17/17 with zero skips, and database contract checks passed 25/25. The original database skips and environment failures remain recorded. Real customer model/page, final cloud image and customer deployment are not covered by this source verification; complete delivery is not claimed.

Existing unit-tests.yaml discovers the new cases; its serial codex-smoke job rejects skipped/failed/error outcomes without a duplicate gate. Output caps, stage/overall deadlines, tool budgets and retry policies remain unchanged; context pages are at most 16000 characters. Rollback uses the previous thoughtfix1 wheel/image without changing stored history.
