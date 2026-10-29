# Confirmed disconnect reported as a transport failure

[中文](2026-10-29-customer-disconnect-transport.zh.md)

Change ID: customer-disconnect-transport. Date: 2026-10-29. Status: approved for local implementation and verification by the user's explicit request to repair same-session continuation after stopping one query. The user subsequently authorized deployment to the specific PDSA Runtime after verification. The original customer Runtime remains frozen.

Components: [customer Runtime](../../../specs/runtime-customer/README.md). Predecessor: [confirmed cancellation](../customer-confirmed-cancellation/2026-10-29-customer-confirmed-cancellation.md).

## Evidence, goals and scope

The application observed interrupted model execution followed by two recovery refusals for the same business Session. The user confirms stopping one query without closing the Session. The initial internal exception ordering is not established by production traces. In `runtime.py`, only `CancelledError`/`GeneratorExit` enter confirmation and settlement; a channel `transport_error` skips that path even when the trusted application has independently observed disconnection.

Repair the common mechanism with a deterministic regression. Preserve the original error, owner identity, journal and stop proof. Do not change public HTTP APIs, Session identifiers, schemas, providers, retry policy, default configuration or historical blocked Sessions. No force unlock, TTL takeover, tool replay or deployment.

## Requirements and scenarios

- FR-1: A `CustomerChannelError` with exactly `transport_error` may reach the existing optional server-owned `confirm_cancellation` hook after Dispatcher, tools, HTTP and journal cleanup. A transport error itself is never stop proof.
- FR-2: The hook must independently verify actual disconnect, fence and stop the exact remote owner, and settle history. Only literal `True`, followed by the existing verified journal/display settlement, allows the same identity's next turn.
- FR-3: Preserve the original transport error for the interrupted request. False/non-boolean/absent/throwing hooks, other channel errors, unresolved tasks and conflicting history retain quarantine.
- FR-4: Keep previous user input and complete evidence, exactly one interrupted terminal, tool-call pairing and stable remote binding. Never replay an old tool or issue a model call to repair cancellation.
- FR-5: Successful requests incur no added callback, network or storage operation. Cancellation cleanup remains bounded by existing limits. No credential or production payload enters evidence.

## Design and component impact

Extend the existing exception handler to accept only the fixed transport-error classification in addition to explicit cancellation. Other `CustomerChannelError` values immediately propagate. Reuse the existing cleanup and `_settle_cancellation`; no new recovery API or callback. The trusted application confirmer already rejects calls without its server-side disconnect flag. The original exception always propagates after attempted settlement.

This amends CON-4/CON-5's eligible failure exits, while preserving confirmation, isolation and persistence requirements. No channel or store schema change. Alternative task-cancellation-count checks are insufficient: the transport reader and Runtime consumer may be different tasks. Treating every network error as healthy or deleting the lock would violate ownership.

## Tasks, tests and acceptance

- T-1 (FR-1–5): review bilingual design and component amendment before code; user authorization covers this narrowly scoped repair, not publication.
- T-2 (FR-1–4): add an actual Runner/HTTP-channel regression that converts a disconnected stream into `transport_error`; bind identical pre-fix and post-fix tests. Cover independently confirmed and unconfirmed cases.
- T-3 (FR-1–5): implement the filtered handler; run affected SDK tests, then required SDK checks and installed consumer/application gates.
- T-4 (FR-2–5): add actual application HTTP disconnect, same-session continuation and persistent-history regression to the mandatory application gate; preserve old failures and report simulated versus deployed results.

AC-1: Pre-fix regression fails because the confirmed Session remains blocked; post-fix identical regression verifies stable remote identity, original input, one interrupted terminal and successful followup. The interrupted request still raises `transport_error`.
AC-2: Unconfirmed ordinary communication failures and unrelated channel errors remain blocked; no new old-turn model/tool sends.
AC-3: Actual application cancellation stops old work and permits the same app/user/session's new query with persistent history. Concurrent activity and unknown stop proof remain refused.
AC-4: Required green checks bind source/artifact digests; unavailable checks are recorded. No online fix is claimed without authorized deployment and original-case acceptance.

## Review, risk and verification

Direct design review (no review-spec skill available): FR-1 is only eligibility; FR-2 owns authorization. Existing callback, cleanup deadline, history validation and error propagation are reused. English/Chinese requirement, task and acceptance IDs match. No design blocker; the explicit user request authorizes local repair and verification.

Risk: a caller-supplied confirmer must honor the pre-existing stop-proof contract. Missing history/ambiguous Host must stay blocked. Production exception ordering remains unverified; a stable mechanism test and application integration must precede a repair claim.

Verification: not_run at design approval. Use targeted `tests/runtime/customer/` checks and the repository's default SDK gates; downstream fixed-wheel native/API/persistent-store gates are required. Real Runtime acceptance is not_run because deployment is prohibited.

## Local verification checkpoint

Devbox2 actual Runner/HTTP: identical final 14 cases on the original module yielded 7 failures and 7 passes; the affected customer Runtime SDK suite passed all 407 cases without skips or source drift. Application real loopback HTTP cancellation and persistent history passed 3 cases in each of the standard and B14 configurations. Identical pre-fix tests failed only transport-error continuation in both configurations. The initial injection order produced no failing regression and is not defect reproduction evidence. Fixed installed consumer, full default SDK gates and live Runtime acceptance are not yet passed; no publication.

Deployment authorization checkpoint: the later explicit user request permits the verified PDSA candidate only. Required gates, installed consumer verification and application APMPlus acceptance remain mandatory; no Runtime was deployed at this checkpoint.

Installed consumer checkpoint: the test wheel was installed into an isolated Devbox2 environment. Installed Python digests and actual import paths matched, without SDK-source PYTHONPATH. Cancellation, continuation, persistent history and deletion after settlement passed 3 cases in both standard and B14, with no skips or tool replay. This artifact is not yet bound to committed source and remains for local consumer verification only.
