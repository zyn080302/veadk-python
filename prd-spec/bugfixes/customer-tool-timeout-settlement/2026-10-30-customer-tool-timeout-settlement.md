# Customer tool timeout settlement

[中文版](2026-10-30-customer-tool-timeout-settlement.zh.md)

Change ID: customer-tool-timeout-settlement. Date: 2026-10-30. Status: approved scope, verification pending.

## Background and authorization

The consumer reported tool timeout without a current reply and subsequent session recovery refusal. Dispatcher cleanup can prove local quiescence, but Runtime excludes tool_timeout from its optional confirmation path. Existing disconnect-only consumer confirmation cannot settle a tool deadline. The user explicitly authorized repairing these failures and publishing the affected consumer Runtime; this change implements that authorized scope. No external resource authorization is added.

## Requirements and design

R1: Exact controlled tool_timeout may request optional server confirmation only after dispatcher, HTTP and pending journal cleanup. Other channel failures remain unchanged. No callback or any result other than literal True retains quarantine.
R2: Add reason to CustomerCancellationContext with default customer_turn_cancelled. The only added reason is tool_timeout; never infer remote stop from the error. The trusted consumer confirms exact owner/step/identity and preserves the original input and prior events.
R3: On confirmed timeout, pair unresolved calls with tool_timeout and side_effects unknown; append an interrupted, turn_complete timeout notice to the durable journal. Preserve cancelled turn storage status as a proof of stopped execution, with the actual reason in its event. No schema migration or retry.
R4: Unlike disconnected cancellation, publish the timeout terminal through Runner once. Persist missing journal prefix and paired receipts before yielding; Runner persists the unique terminal, then verify and acknowledge display before releasing ownership. A failed or cancelled publication retains recovery requirements. Unconfirmed timeout preserves the original exception.
R5: User cancellation, transport-disconnect confirmation, normal completion, identity isolation and changed-history rejection retain their existing behavior.

## Tasks, files and acceptance

T1: Add red shared/native Runner regressions with real executor deadlines, cleanup proof, original history, exact terminal and same-session followup; cover refused/throwing confirmation and no callback.
T2: Update cancellation.py and runtime.py; update runtime-customer and runtime-customer-session-store bilingual contracts. Dispatcher and channel deadlines are not relaxed.
T3: Run affected SDK tests, full required SDK gates and installed consumer two-process/persistent HTTP regressions before publication. Record actual outcomes here; offline success does not prove deployed behavior.
A1: No executor replay, no force unlock, exactly one persisted current timeout terminal, original input and prior history preserved, followup uses the same binding.
A2: Ambiguous stop or storage conflict remains quarantined; all existing cancellation tests pass.

## Review, compatibility and risks

Direct review (review-spec skill unavailable): optional confirmer preserves defaults and authoritative stop proof. New context field is defaulted for compatibility. No credentials, routing values or provider errors enter events. Yield/storage ordering is the main risk and requires real Runner plus persistent consumer coverage. Scope authorization is the existing explicit user repair/publish instruction; no new approval is required within this scope. Broader total/runtime timeout settlement is outside this change.

## Verification

Implemented against R1–R5. Identical real deadline regressions failed before the change (8 failing / 2 passing cases) and passed after it; affected customer suite: 417 passed. Default parallel SDK regression with two workers: 7,979 passed, 50 skipped, 4 xfailed, 6 subtests passed; tested Python source manifest remains unchanged. An isolated wheel was verified for consumer testing only. Installed consumer standard/B14 persistent HTTP acceptance: four cases passed per profile, zero skipped, isolated wheel imports and Python sources verified, processes stopped. The Host fixture override was corrected to forward the optional reason keyword; authoritative stop proof and all history/followup/no-replay assertions remain mandatory. Repository hooks, formal source-bound artifact, deployed acceptance and publication are pending. No deployed fix is claimed.
