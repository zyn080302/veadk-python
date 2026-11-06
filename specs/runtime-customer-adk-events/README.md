# Customer ADK display event stream

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-adk-events/README.zh.md)

Component ID: `runtime-customer-adk-events`; revision: 2026-10-20; status: active.
Code/tests: `veadk/runtime/customer/events.py`, `tests/runtime/customer/test_events.py`.
Design/evidence: [customer-adk-events](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-adk-events/2026-10-20-customer-adk-events.md).

## Responsibility and public entry

`from veadk.runtime.customer import CustomerAdkEventStream`. Owns one `CustomerToolDispatcher` context and converts its observed `run.event` records into ADK display Events. Dispatcher owns execution/ACK/cancellation; Runner owns local persistence; Host owns reasoning history. No Agent runtime registration, business identity, model loop, tool callback/state bridge, replay, session migration, media output, interactive tool authorization or multi-agent support is provided by this component.

```python
async with CustomerAdkEventStream(
    dispatcher, author="assistant", invocation_id="local-invocation",
    new_message={"role": "user", "parts": [{"text": "Hello"}]},
    branch=None,
) as stream:
    async for event in stream.events():
        await persist_or_send(event)  # Caller error exits and cancels the run.
```

## Contracts

| ID | Contract |
| --- | --- |
| CON-1 | Constructor snapshots a nonempty user Content (Shared text-only; native input follows runtime-customer CON-8) and validates local author/invocation/optional branch. Context and `events()` are each single-use; enter first, consume and exit in the same asyncio task. Exceptions propagate; remote-derived diagnostics contain fixed codes only. |
| CON-2 | Initial identical user echo is discarded once. Different/repeated/late user events fail. All output uses local author/invocation/branch and fresh Event ID/time. Remote actions/state/routing/auth/signatures and arbitrary metadata are never copied. Only the display-purpose whitelist in CON-7 may be preserved. This does not sanitize arbitrary business text or tool values: executors/Host must already redact secrets. |
| CON-3 | Only text with optional thought flag, complete functionCall/functionResponse and five nonnegative integer usage counters (promptTokenCount, candidatesTokenCount, totalTokenCount, cachedContentTokenCount, thoughtsTokenCount, each at most 2^53-1) are projected. Snake case aliases also accepted, ambiguous aliases rejected. No usage is copied from partial snapshots. Unknown content parts or malformed shapes fail. Pure thought/usage events are partial display only; they are not final answers. |
| CON-4 | Complete function IDs must be nonempty strings up to 128 chars; names up to 64 match each response. Map to fresh local IDs; at most 64 open/1024 total calls. Display never executes tools, does not correlate with channel request_id and must not create another local tool display stream. Duplicate/orphan responses, duplicate call IDs, partial tool fragments, long-running/auth/confirmation events and success with open calls fail explicitly. Remote callback state is not applied locally. |
| CON-5 | A complete plain answer is held, never synthesized from partial text. Exactly one final is required; no content may follow it (usage-only events may follow). Release it only after dispatcher success and successful context cleanup. Errors/interruption/cancel/EOF/ACK/cleanup failure discard it. Empty content is final only with explicit turnComplete=true. Final output has turn_complete=true; earlier output does not. |
| CON-6 | At most 4096 raw run events, each 1 MiB of JSON; duplicate complete remote Event IDs fail. Only bounded ID sets/maps and one final Event are retained. No persistence/restart guarantees, no retries or resumable iterator. Caller persistence failure requires fresh invocation/reconciliation, never re-consuming the same stream. |

## State, isolation and failures

States: constructed → entered → consuming → closed. A final is yielded only after dispatcher closure; outer stream context still closes its generator. Consumer exceptions close the generator before closing the dispatcher in the same task. Dispatcher `cleanup_timeout` and `quiescent` obligations remain: callers must quarantine non-cooperative contexts until stopped. Closing an unused entered stream also cancels its dispatcher. Re-entry/concurrent iteration is rejected.

Error codes include `invalid_adk_event`, `unsupported_adk_content`, `unexpected_user_event`, `remote_event_error`, `remote_event_interrupted`, `invalid_display_tool_call`, `invalid_display_tool_response`, `unsupported_partial_tool_event`, `unsupported_interactive_event`, `too_many_adk_events`, `adk_event_too_large`, `duplicate_adk_event`, `missing_final_response`, `multiple_final_responses`, `event_after_final`, `unresolved_display_tools`, and lifecycle errors. Errors contain no input values. HTTP/dispatch errors retain their fixed codes. No logs or metrics are added.

## Compatibility and verification

Additive opt-in API; existing runtime and channel behavior unchanged. Plain single-agent Shared ADK JSON only; unsupported Host versions/capabilities require explicit adaptation, not coercion. Local tests use actual ADK serialization and Runner persistence plus dispatcher fixtures. Contract mapping: CON-1/CON-6 lifecycle/limits; CON-2 trust/echo; CON-3 content/usage; CON-4 tools; CON-5 terminal/ACK/cleanup. Existing Harness release gate includes `tests/runtime/customer`. Verification status is maintained in the linked design; a fixture pass is not live Runtime acceptance.

Native Runtime integration: a private Python local-event batch shares the bounded dispatcher queue. It is never parsed from remote JSON. Native result submission waits for the Runtime journal/yield acknowledgement; cancellation, queue overflow and journal failure stop submission. Native mode validates remote display for locally registered tool names but emits the local completed call/response pair instead; Host-only tool display is preserved. Local state is governed by [runtime-customer CON-7](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.md). Existing explicit-executor display behavior is unchanged.


## Native protocol extension (2026-10-20)

Implemented and verified by targeted/full local regression. [Design and evidence](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-channel/2026-10-20-customer-native-channel.md) defines protocol="native" opt-in, /apps + /run_sse, exact result-echo ACK, multi-HTTP deadlines and binding isolation. Shared defaults remain unchanged. The channel validates and normalizes deferred calls/verified response echoes before existing display projection. Execution permits end before ACK waiting to avoid batch deadlock; deadlines and final-after-ACK remain. Store schema and incomplete-turn quarantine remain unchanged. No claim of full Skill/attachment support, crash recovery or production acceptance.


## Native attachment extension (2026-10-20)

SDK implementation, full regression and fixed Host source integration verified; fixed business artifact acceptance pending: [customer-native-attachments](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-attachments/2026-10-20-customer-native-attachments.md). Native input gains bounded original media and opaque metadata; Shared remains text-only. Runtime uses a separate 8 MiB native initial envelope; client max_initial_request_bytes=None inherits max_request_bytes. Tool batches remain 2 MiB and output events 1 MiB by default. Original input stays in ADK/Host history; journal/recovery schemas and output content are unchanged. The linked design owns exact limits and acceptance.


## Approved final-answer purpose (2026-10-24, proposed)

CON-7: only `customMetadata.skyeyes_output_purpose` (or unambiguous `custom_metadata`) may be copied, as a fresh object with exactly `version: 1` (integer, not bool/float) and `purpose: "final_answer"`. The label requires nonempty model text parts without thought or tools; user echoes and contentless events cannot carry it. Malformed reserved labels or incompatible content fail with `invalid_output_purpose`; conflicting aliases fail with `invalid_adk_event`. Other metadata stays excluded. This label is display-only: it changes no identity, tool permission, actions, terminal/cleanup rule or final-text generation. Approval belongs to the trusted configured Host, not SDK inference. Existing users without this label retain their prior behavior.

Design and pending verification: [customer-final-answer-purpose](../../prd-spec/bugfixes/customer-final-answer-purpose/2026-10-24-customer-final-answer-purpose.md). Tests: `tests/runtime/customer/test_output_purpose.py`, with existing event/Runtime regressions. A new installed SDK artifact and downstream Host/HTTP/history/browser acceptance are required before business delivery.


## Incomplete business terminal (2026-11-06, implemented and offline verified)

CON-8: Extend CON-2 whitelist with exactly `skyeyes_result: {status: "incomplete", reason: "model_tool_protocol_error" | "host_turn_budget_exhausted" | "research_delivery_review_rejected"}`. Malformed markers fail with fixed `invalid_result_status`, aliases remain unambiguous. Require nonpartial explicit turnComplete=true model text without thoughts/tools, empty model parts, or contentless terminal. A contentless marked event participates in CON-5 held-final/ACK/cleanup and duplicate/late-final rules. Persisted completion is transport settlement; this display marker denotes business incompleteness and grants no state, identity, permission or retry. Consumer must display incomplete in SSE/history while keeping normal/future invocations independent. [Approved design](../../prd-spec/bugfixes/customer-incomplete-terminal/2026-11-06-customer-incomplete-terminal.md). Tests: `tests/runtime/customer/test_incomplete_terminal.py`, mandatory existing Harness customer directory. Fixed artifact/downstream/live acceptance pending.


CON-9: Extend the display-only whitelist with exactly `skyeyes_research_delivery: {version:1, model_reported:true, outcome:"answer"|"partial"|"clarification", requirements:int(1..128), unknown:int(0..requirements)}`. Boolean counts/version are invalid. Answer requires zero unknown, the other outcomes require at least one. Require nonpartial model public pure-text body; explicit remote turnComplete=false is rejected, absent remote completion remains compatible. Hold the final until successful transport completion/result ACK/dispatcher cleanup, then journal before display. Reject malformed reserved markers with fixed `invalid_research_delivery`; import no remote identity, state, facts or authority. Consumers preserve status in SSE/history and separate transport settlement from business partial and independent recovery admission. No store schema or public API changes. Tests: `tests/runtime/customer/test_business_delivery_status.py`; mandatory existing Harness customer directory. [Approved design](../../prd-spec/bugfixes/customer-business-partial-status/2026-11-06-customer-business-partial-status.md).


Review rejection reason compatibility: the third reason preserves business incompleteness without changing terminal, identity, permission or retry checks. New mandatory regression: `tests/runtime/customer/test_review_rejection_terminal.py`. [Approved design](../../prd-spec/bugfixes/customer-review-rejection-terminal/2026-11-06-customer-review-rejection-terminal.md).
