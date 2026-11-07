# Customer factual closeout reason compatibility

[中文](2026-11-07-customer-factual-closeout-reasons.zh.md)

Change ID: customer-factual-closeout-reasons; date: 2026-11-07; status: approved for isolated implementation.

## Background, scope and approval

The authorized SkyEyes factual-closeout Agent emits three legal `skyeyes_result` reasons that fixed dev21 rejects in `_display_metadata`: `model_request_failed`, `turn_deadline_exceeded`, `host_execution_failed`. This confirmed consumer compatibility failure is independent from attribution of the original customer interruption. The main agent explicitly authorizes this exact-base isolated SDK fix, commit, offline wheel build and independent installed validation. The base is `8b0bc84e7b210468336d97cfcfe4b06b4cd65cf5`. Original source, environment and wheel remain unchanged. No network, model/MCP/business requests, deployment or remote shell; offline exact-base authorization supersedes generic pull/fetch/rebase requirements.

## Requirements and design

FR-1: Extend only the strict reason set in `veadk/runtime/customer/events.py::_display_metadata` by those three reasons. Status remains `incomplete`. Keep the three old reasons, exact marker shape, unknown rejection, alias rules and local identity.

FR-2: Preserve held-final completion, transport/result ACK and cleanup, durable journal ownership, replay/display acknowledgement and next-turn admission. The marker grants no permissions, facts, execution retry or business-success certification. No schema, timeout, public signature or dependency change.

FR-3: Add identical regression tests before production edits using actual ADK serialization, event projection/dispatcher, SQLite journal/reconnect/history, display acknowledgement and a successful next turn. Cover all six reasons, malformed/unknown markers, partial/tool/thought/user/alias rejection and transport failure. Existing mandatory Harness `tests/runtime/customer` directory executes the new tests.

FR-4: Build a separately versioned immutable wheel from the committed source using the previously audited offline build flow; verify source/receipt/wheel and independently installed package. Keep the existing approved messages.py PDF overlay outside the wheel. Main reviews the new artifact and application locks/manifests; do not edit historical receipts or shared pins.

## Component impact, tasks and acceptance

Runtime-customer-adk-events CON-8 owns this display reason set; update its paired spec. Session-store schema and state contracts remain unchanged. AC-1: original production rejects new reasons while old reasons and strict negative controls pass. AC-2: same tests pass with all markers remaining incomplete and no external network. AC-3: affected customer/cleanup regressions, lint/format/diff checks and installed verification pass or are accurately recorded as not_run/blocked. AC-4: deliver exact commit/parent, source/test hashes and internal complete source; template SDK source is not a customer package. Actual page/API/APM acceptance belongs to main/original owner after new Ready; offline SDK passes do not complete that feature.

## Design review and risks

Review-spec skill is unavailable; equivalent direct review checks bilingual equivalence, exact bounded reasons, unchanged ownership/terminal/ACK/cleanup/isolation, old-reason compatibility, failure-layer tests and no external requests. No blockers; main's explicit narrow-fix authorization approves this design before test/production edits. Unknown future reasons remain rejected and need a separate reviewed contract. Full repository/pre-commit/live checks may be outside this exact offline task and must not be claimed as green.

## Verification

Pending red/green and isolated installed evidence in the local delivery directory. Exact execution counts and results will be recorded after execution.

Executed 2026-11-07: final identical145 tests parent121pass/24fail, candidate145pass; new test SHA646a7128043699cd6901b39e6be00eb8437be85e16201a511a94e3f98fe429ea unchanged. Mandatory customer directory/Runtime cleanup625pass,0skip,41loopback/0external; events SHA08ec92db8329166166e8f4bc098fefcdd5b4a8ad5488199c0d30fc8d92d8137f. Changed Python Ruff check/format passed. Initial generated fixture collection error retained and corrected before final red, not counted as mechanism failure. All3713 original dev21 source digests match. Separate artifact/installed verification follows; full repository/pre-commit/live page/API/APM not_run under this exact offline scope.
