# Customer ADK display event stream

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-adk-events/README.zh.md)

Component ID: `runtime-customer-adk-events`; revision: 2026-10-20; status: active.
Code/tests: `veadk/runtime/customer/events.py`, `tests/runtime/customer/test_events.py`.
Design/evidence: [customer-adk-events](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-adk-events/2026-10-20-customer-adk-events.md).

## Responsibility and public entry

`from veadk.runtime.customer import CustomerAdkEventStream`. Owns one `CustomerToolDispatcher` context and converts its observed `run.event` records into ADK display Events. Dispatcher owns execution/ACK/cancellation; Runner owns local persistence; Host owns reasoning history. No Agent runtime registration, business identity, model loop, tool callback/state bridge, replay, session migration, attachments, interactive tool authorization or multi-agent support is provided by this component.

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
| CON-1 | Constructor snapshots a nonempty text-only user Content and validates local author/invocation/optional branch. Context and `events()` are each single-use; enter first, consume and exit in the same asyncio task. Exceptions propagate; remote-derived diagnostics contain fixed codes only. |
| CON-2 | Initial identical user echo is discarded once. Different/repeated/late user events fail. All output uses local author/invocation/branch and fresh Event ID/time. Remote actions/state/metadata/routing/auth/signatures are never copied. This does not sanitize arbitrary business text or tool values: executors/Host must already redact secrets. |
| CON-3 | Only text with optional thought flag, complete functionCall/functionResponse and five nonnegative integer usage counters (promptTokenCount, candidatesTokenCount, totalTokenCount, cachedContentTokenCount, thoughtsTokenCount, each at most 2^53-1) are projected. Snake case aliases also accepted, ambiguous aliases rejected. No usage is copied from partial snapshots. Unknown content parts or malformed shapes fail. Pure thought/usage events are partial display only; they are not final answers. |
| CON-4 | Complete function IDs must be nonempty strings up to 128 chars; names up to 64 match each response. Map to fresh local IDs; at most 64 open/1024 total calls. Display never executes tools, does not correlate with channel request_id and must not create another local tool display stream. Duplicate/orphan responses, duplicate call IDs, partial tool fragments, long-running/auth/confirmation events and success with open calls fail explicitly. Remote callback state is not applied locally. |
| CON-5 | A complete plain answer is held, never synthesized from partial text. Exactly one final is required; no content may follow it (usage-only events may follow). Release it only after dispatcher success and successful context cleanup. Errors/interruption/cancel/EOF/ACK/cleanup failure discard it. Empty content is final only with explicit turnComplete=true. Final output has turn_complete=true; earlier output does not. |
| CON-6 | At most 4096 raw run events, each 1 MiB of JSON; duplicate complete remote Event IDs fail. Only bounded ID sets/maps and one final Event are retained. No persistence/restart guarantees, no retries or resumable iterator. Caller persistence failure requires fresh invocation/reconciliation, never re-consuming the same stream. |

## State, isolation and failures

States: constructed → entered → consuming → closed. A final is yielded only after dispatcher closure; outer stream context still closes its generator. Consumer exceptions close the generator before closing the dispatcher in the same task. Dispatcher `cleanup_timeout` and `quiescent` obligations remain: callers must quarantine non-cooperative contexts until stopped. Closing an unused entered stream also cancels its dispatcher. Re-entry/concurrent iteration is rejected.

Error codes include `invalid_adk_event`, `unsupported_adk_content`, `unexpected_user_event`, `remote_event_error`, `remote_event_interrupted`, `invalid_display_tool_call`, `invalid_display_tool_response`, `unsupported_partial_tool_event`, `unsupported_interactive_event`, `too_many_adk_events`, `adk_event_too_large`, `duplicate_adk_event`, `missing_final_response`, `multiple_final_responses`, `event_after_final`, `unresolved_display_tools`, and lifecycle errors. Errors contain no input values. HTTP/dispatch errors retain their fixed codes. No logs or metrics are added.

## Compatibility and verification

Additive opt-in API; existing runtime and channel behavior unchanged. Plain single-agent Shared ADK JSON only; unsupported Host versions/capabilities require explicit adaptation, not coercion. Local tests use actual ADK serialization and Runner persistence plus dispatcher fixtures. Contract mapping: CON-1/CON-6 lifecycle/limits; CON-2 trust/echo; CON-3 content/usage; CON-4 tools; CON-5 terminal/ACK/cleanup. Existing Harness release gate includes `tests/runtime/customer`. Verification status is maintained in the linked design; a fixture pass is not live Runtime acceptance.
