# Codex input context

[中文版](README.zh.md)

ID: codex-input-context. Status: draft (implementation pending). Revision: 2026-11-26.

Owns Codex RPC text packing in `veadk/runtime/codex/input_context.py` and runtime wiring. It does not own model reasoning, customer tools, session storage or approvals.

CON-1: Inputs at most 1,048,576 Unicode characters including the shim marker pass unchanged. Overflow preserves exact source in invocation-local memory and substitutes a bounded Markdown request with explicit excerpt labels and a source reference. Current question and recent evidence remain represented; no knowledge-base count limit.

CON-2: `_veadk_read_context(reference: str, offset: int = 0, length: int = 16000, query: str = "")` returns a JSON tool result with `status`, `text`, `offset`, `next_offset`, `total_characters` and optional search status. The machine consumer is MCP/ADK; structured fields support exact paging and distinguish no match from unavailable. Maximum page 16000 characters; query at most 256 characters; integers exclude booleans and offsets cannot exceed source length. The reader accesses only the current invocation map; no global cache/files/network. A reference is not a persistent citation.

CON-3: Dispatch retains existing callbacks, tool budgets/timeouts and cancellation. No new model phase, retry or increased deadline/cap. Original session records remain unchanged. Context-reader events are excluded from subsequent input replay to prevent recursive duplication. Latest source references accompany resumed turns when the full replay is oversized. Unknown/expired references are explicit failures, never evidence of absence.

CON-4: Never archive privileged instructions, credentials obtained outside the already-authorized input, or hidden reasoning. Use existing visible-content filtering. Do not normalize instruction hashes; actual instruction changes still restart threads. Normal attachment handling and thinking classification remain unchanged.

Verification: `tests/runtime/codex/test_codex_input_context.py` and `test_codex_input_context_smoke.py`, existing unit-tests and serial Codex smoke jobs. Direct and shim transport consumers must both be checked. See [design](../../prd-spec/bugfixes/codex-input-length/2026-11-26-context-reader.md) for execution results and limits. No cloud/customer acceptance claimed.
