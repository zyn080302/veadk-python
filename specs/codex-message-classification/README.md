# Codex message classification

[中文](README.zh.md)

Component ID: codex-message-classification. Revision: 2026-11-25. Status: SDK repair and mandatory local gates verified; not deployed.

Owns Codex translation/final selection and thought labels at telemetry export boundaries. Consumers: Runner, callbacks, session history and BFF answer collectors. Model/provider labeling and callback-generated content remain their respective owners' responsibilities.

- CON-1: item start/completion retain custom_metadata.phase. notification_to_events accepts optional item_phases mapping scoped to one turn; no global state. Deltas correlate by item ID; completion removes that entry. Commentary/partial_answer/unknown deltas carry text in custom_metadata.text and no content. They remain partial and are not persisted. Real reasoning keeps Part.thought=True; it is not inferred from words.
- CON-2: Explicit final_answer deltas have ordinary text content. Final selection takes the last completed explicit final_answer; otherwise the last unphased completed agentMessage. Batch translation agrees. Earlier candidate text never enters the single final callback/event. Legacy unphased deltas wait for final selection; existing callers need no signature changes. Unknown phase does not become an answer.
- CON-3: Completion gen_ai.completion.N.type and assistant/choice parts.N.type use reasoning for thought and text otherwise. Existing content-tracing controls govern collection; no additional reasoning text is collected.
- CON-4: No new I/O, configuration, retries, deadlines or permissions. Existing cancellation/error/tool paths remain. Per-turn state is discarded when the pump exits, including errors. Session identity isolation and tool history are unchanged. No retrospective cleanup of old sessions.

Supported verification targets: unchanged Codex0.159.2 repository pin and original deployment0.162.1. Existing APM text consumers retain original content keys with additive classification; BFF may consume progress metadata explicitly but must not treat it as final text. Unknown upstream mixed ordinary text remains unclassifiable without authoritative labels.

CON-1/2: tests/runtime/codex/test_codex_message_classification.py and local-process smoke. CON-3: tests/test_tracing_content.py. CON-4: existing Codex cancellation/turn suites. Mandatory unit-tests workflow discovers these tests. Real customer acceptance requires separately authorized deployment.

Change and evidence: [approved repair](../../prd-spec/bugfixes/codex-message-classification/2026-11-25-phase-and-thought.md).
