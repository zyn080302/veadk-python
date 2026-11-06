# Customer review rejection terminal compatibility

[中文](2026-11-06-customer-review-rejection-terminal.zh.md)
Change ID: customer-review-rejection-terminal; date: 2026-11-06; status: approved for isolated implementation.

## Background and evidence
The actual SkyEyes scoped review callback emits `ResearchDeliveryReviewRejected` with exactly `skyeyes_result: {status: "incomplete", reason: "research_delivery_review_rejected"}`. The fixed SDK rejects this legal reason with `invalid_result_status`; the real SDK/SSE/SQL/history integration test fails before the public incomplete notice can be displayed. This is a confirmed SDK consumer compatibility mechanism; it is not attribution of the original customer incident. The new business classification is `research_delivery_review_incomplete`, independent from model/tool protocol errors.

## Goals, boundaries and scenarios
Preserve a legitimate review rejection as business incomplete through serialization, display projection, transport settlement, durable history and display acknowledgement. Never turn it into business success or enable retry, state, identity or permission. User authorizes high-priority bugfix/integration; the main agent explicitly delegates this isolated one-reason compatibility fix. The main agent owns wheel assembly/pinning, merge, PDSA release and original live badcase acceptance. No shared SDK installation, dependency/version changes, frozen-tree edits, model/network calls, deployment or remote shell are authorized for this worker.
A public model stop notice and an empty/contentless marked terminal must settle only after dispatcher completion and successful cleanup. Unknown reasons, invalid status, forged marker fields, drafts, tool/thought/user events and ambiguous metadata remain rejected. Normal completion and fresh sessions/invocations remain independent.

## Requirements and design
FR-1: Add only `research_delivery_review_rejected` to the existing strict `_display_metadata` reason set. Preserve exact two-key shape/status validation, alias ambiguity, fresh copy and local identity mapping. Keep the existing protocol/budget reasons.
FR-2: Use the same validator at durable completion; do not alter held-final, ACK, cleanup, cancellation, journal ownership or recovery admission. Transport completion is independent from business incompleteness.
FR-3: Add same-test red/green regressions through real ADK serialization, CustomerAdkEventStream/dispatcher, SQLite storage/reconnection/history/display acknowledgement, cross-identity isolation and an independent successful next turn. Keep strict marker/content failures and existing protocol tests. Existing mandatory Harness `tests/runtime/customer` directory includes the new test file; no gate bypass is required.
CON-8 in the bilingual runtime-customer-adk-events component spec owns the reason whitelist; only this whitelist changes. No public API/store schema/configuration or unrelated component changes.

## Tasks, acceptance and review
T-1/AC-1: Bind the isolated 3710-file source to the exact fixed artifact source manifest; retain unchanged source/tests and shared environment.
T-2/AC-2: Write new regressions first; demonstrate legal new-reason failures against unchanged production code, then run the identical tests against the narrow candidate with zero failures/skips.
T-3/AC-3: Run mandatory customer directory and adjacent Runtime cleanup tests, changed-file Ruff, paired-document/diff checks. Delegate real business SDK/SSE/SQL/history and native outer regressions to the owning contextual worker using an isolated source import, without editing shared SDK.
T-4: Deliver independently reviewable delta, exact source/test hashes and real counts, a complete internal source candidate package and a deterministic build helper. Wheel creation/pinning/live acceptance remain main responsibilities; no release readiness claim from offline tests.
Review-spec is unavailable. Equivalent direct review confirms bilingual equivalence, strict bounded reason set, all terminal/identity/ownership checks unchanged, no new dependencies, fixture-only external services and actual failure-layer regression. No design blockers. Existing user task and main narrow-fix authorization approve this approach; they supersede repository requests for another approval and remote source synchronization. Accurate fixed source must not drift by pull/rebase. Review completed before production or test edits.

## Risks and verification
Old artifacts continue to reject the new reason. Main must build and pin a new immutable artifact rather than refresh an old hash. Unknown future reasons remain errors and require separate contract review. Full repository tests/pre-commit/live Runtime not yet run; findings and actual execution evidence will be added after testing. The internal package includes template SDK source and is not a customer deliverable.

Verification 2026-11-06: fixed source/installed event bytes match; source manifest 3710 files verified without mismatch. New/adjacent targeted tests49: unchanged production39 pass/10 fail, candidate49 pass/0skip, no external network. Full mandatory customer+Runtime cleanup529 pass/0skip,41 loopback connections/0external. Changed-file Ruff check passes; format was subsequently applied only to the new test, whose final unchanged-parent red reproduces the same10 failures. Actual installed-candidate verification is pending separate main-authorized dev21 build; source-only passes do not prove Host child processes use that artifact. Full repository/pre-commit/live acceptance not_run.
