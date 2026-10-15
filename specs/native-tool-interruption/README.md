# Native tool interruption

[中文版](README.zh.md)

Component: native-tool-interruption; date: 2026-10-15; status: implemented (offline verified).
Owned code: veadk/runtime/codex/mcp_bridge.py, runtime.py and execution_control.py. Tests: tests/runtime/codex/test_codex_mcp_bridge.py; downstream Harness native protocol tests.

CON-1: An optional internal register_turn on_interrupt async callback receives no content or credentials. For an existing INTERRUPT_STATUSES result, record the state then await the callback before returning placeholder text. Ordinary results do not invoke it. Omitted callback preserves existing bridge behavior.
CON-2: The runtime callback requests interruption through the native turn API once per invocation. ADK owns call events, resumed results and session state; no extra history store or loop is added. Concurrent turns never share callback state.
CON-3: TurnInterrupt uses an asyncio.Lock so concurrent calls in one turn share one confirmation; done is set only after success. Failure or cancellation is retained and re-raised to later callers, never reported as success. No background task is created. Cancellation propagates. Callback failures are recorded in turn state and notify on_error; MCP returns only a generic error, never exception details or a successful placeholder. Tool admission, tokens, budgets and timeout ownership are unchanged. Existing event-consumer interruption remains as a fallback using the same callback.

Verification: real loopback MCP ordering assertions, success and independent-turn controls; downstream real native client-tool protocol roundtrip. Full gates and cloud validation recorded in the linked [PRD](../../prd-spec/bugfixes/native-tool-interruption/2026-10-15-pending-tool-interrupt-order.md). No new public config, environment, telemetry or dependency.
