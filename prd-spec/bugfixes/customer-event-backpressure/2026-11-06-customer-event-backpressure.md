# Customer event queue coordination

Counterpart: [中文](2026-11-06-customer-event-backpressure.zh.md).
Date: 2026-11-06. Status: implemented and offline verified; fixed-artifact integration pending.

## Evidence, goals and boundaries

The fixed installed dispatcher and pinned source agree: `_emit` and `_emit_local` call `put_nowait`; a brief slow consumer raises `event_backpressure` before existing turn/tool deadlines. The customer incident has no bound queue timeline: `root_cause_event=null`, attribution abstains. This mechanism reproduction is not accident causality.

The user explicitly authorizes this isolated SDK queue repair, complete slow-consumer/burst/native accepted/cancellation/deadline/exit regressions and mandatory gates. Main owns fixed-artifact integration and PDSA; BugFix2 owns Runtime consumer terminal/recovery. Existing person-gate/V8 releases proceed independently. No deployment, push, live model/MCP, remote shell, resource enumeration or shared SDK edits.

## Requirements and design

- REQ-1: Preserve bounded FIFO/default16/max256, event content/order/usage and all local call-response pairs. Use interruptible `await queue.put` instead of capacity failure. No coalescing, drop or unbounded event buffer; the current reader naturally applies transport flow control. Pending local producers are already bounded by the64-job limit.
- REQ-2: Queue puts and native `accepted` waits remain inside existing owner turn deadline and executor tool deadline. No independent timeout extension. Execution permits retain existing release-before-remote-ACK behavior. A stopped consumer cannot create an infinite production wait.
- REQ-3: Success still follows all required result ACKs and validated Host terminal. Exceptions remain owner/failure state, independent of data capacity, and preempt buffered events. No synthetic success or public payload/schema change.
- REQ-4: Closing/cancelling the event iterator cancels owner, revokes submissions and joins owned children within existing shared cleanup deadline. Late producers cannot resume a closed consumer. Cooperative tasks settle; noncooperative tasks keep cleanup_timeout/quarantine, not false quiescence.
- REQ-5: Use actual dispatcher, native ADK projection/Runtime/Runner and business slow-persistence consumer paths. Preserve incremental SSE: first partial reaches consumer before Host terminal. Cancel and deadline tests hold the queue full with explicit barriers. Native call publication must complete accepted/journal sequence without duplicate execution.

Affected code: `veadk/runtime/customer/dispatch.py`; tests in `tests/runtime/customer/test_event_backpressure.py` and existing stall-negative regression in `test_dispatch.py`. No runtime.py ownership change. The component spec CON-3 replaces immediate capacity failure with cancellable deadline-bound coordination; CON-4/5 are maintained. Business gate and artifact review are separately prepared for main integration.

## Tasks, verification and acceptance

1. Preserve fixed SDK source/artifact baseline; isolate package copy and business worktree.
2. Review paired design/spec before test/code edits; add deterministic actual-path regressions and retain same-test red.
3. Implement only queue coordination/iterator exit, run same-test green, full customer Runtime tests and affected release-gate checks.
4. Review bilingual consistency, scheduling races, ACK, boundedness, failures and cleanup; run pre-commit as repository tooling permits, preserve blocked/not_run outcomes.
5. Register new business/SDK regressions in existing mandatory release gates; deliver exact commits/patches, source hashes and complete internal code.

Acceptance requires complete ordered events with queue high-water <= configured capacity, incremental partials before terminal, exactly-once tool invocation/result ACK, reachable original sanitized error despite capacity, deadline/consumer exit/cancellation bounded cleanup and no late submission. Tests use synthetic data and mock/local HTTP only. Full original-badcase/PDSA/customer deployment acceptance is not executed here.

## Review, authorization, compatibility and risks

Direct review (review-spec unavailable) checks design/spec equivalence, same-owner cancel scopes, native accepted cycle, finite producer count, transport backpressure and error precedence. No blocker at design checkpoint; any discovered scope/API change returns to review. User's explicit 2026-11-06 instruction supplies requirement/design authorization; no extra permission gate inferred.

A remote cancellation physically behind blocked data is read after flow control permits it; already-received tool.cancel and external task cancellation/deadline stay interruptible. Reading arbitrary future control events without consuming earlier data would need another unbounded buffer; this change does not claim that guarantee. Slow consumers may reach the existing real deadline; that remains failure, never success. Existing `event_backpressure` code may still be recognized by consumers, but transient capacity exhaustion is no longer itself a failure.

Verification 2026-11-06: same-test SHA fed82d45, baseline 6 failed/1 passed (5.418s), candidate 7 passed (3.635s); full customer + Runtime cleanup 453 passed (22.018s), complete affected Harness checks 579 passed (36.774s). Repository all-files pre-commit passed all five hooks (59.037s). Real business Runtime/Runner/JoinedStreamingResponse 3 tests and installed standard/B14 entry integration are separately source-bound in the business candidate. The synthetic business fixture uses a 5s turn/tool limit to allow import/instrumentation overhead; production 165s and suite150/240s limits are unchanged. Remote synchronization intentionally uses the user-pinned ae982106 fixed artifact source, not an unrelated remote head. Full repository unrelated unit suites not_run: only the affected Harness gate is authorized and prepared. Live acceptance not_run by user scope; original accident attribution abstain.

Source-bound receipts: [summary.json](summary.json).
