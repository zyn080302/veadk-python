# Pending tool interruption ordering

[中文版](2026-10-15-pending-tool-interrupt-order.zh.md)

Change ID: native-tool-interruption; date: 2026-10-15; status: approved.
Contract: [native-tool-interruption](../../../specs/native-tool-interruption/README.md).

## Evidence and scope
Harness native Responses client-tool regression observed two upstream requests before the caller supplied a tool result. McpBridge records pending state then immediately returns a placeholder; runtime.py interrupts only after another event reaches its consumer. This races the native next request.

## Requirements and design
FR-1: For pending/authentication_required/confirmation_required/transferred, await a turn-local interruption hook before returning the MCP placeholder. FR-2: Preserve the original ADK call event and caller-owned result, no synthetic completion. FR-3: Ordinary completed tools, namespace admission, budgets and independent turns retain behavior. No new loop, configuration, retries or provider-specific branch.
The optional internal McpBridge.register_turn(on_interrupt=...) callback calls the existing turn.interrupt API. Record interruption state before awaiting it. Native runtime uses a shared idempotent callback for both bridge and existing event-consumer checks. Cancellation propagates; no background task is detached.

## Tasks and acceptance
T-1/AC-1: Bridge HTTP ordering regression for all interrupt states and unaffected successful turns. T-2/AC-2: Wire runtime callback and verify real native Harness Responses/Messages/Chat call-result continuation with one upstream request per turn. T-3/AC-3: Run affected bridge/runtime tests, mandatory Python regression, native smoke and pre-commit. T-4: Reconcile bilingual docs.

## Risks, review and authorization
Interrupt may cancel the in-flight tool handler; retain the already emitted ADK event and test cleanup. Callback errors must not create successful results. Compatibility is additive and internal; no frontend or dependency change. Direct review found no unresolved design blocker. User authorized completing all compatible Harness capabilities and fixes in this session; no additional design approval is required. Production/cloud verification remains restricted to the existing 5663 target; credentials remain local.

## Verification record
2026-10-15: The failing native client-tool regression reproduced an extra upstream request. After the fix, bridge tests passed (33 passed, 1 skipped), including all four wait states, concurrent confirmation, callback failure and cancellation. Downstream Harness native tests passed (15 tests), including three protocol call/result roundtrips with one upstream request per turn, Workflow resume and bidirectional A2A.

`python -m pytest tests -q`: 7136 passed, 50 skipped, 4 xfailed; 6 subtests passed. Run in an isolated environment with telemetry enabled so tracing/metrics tests exercise real initialization. The first run with OTEL_SDK_DISABLED=true caused 65 telemetry test failures; all 65 passed on recheck and the complete rerun passed. `CODEX_RUN_SMOKE=1 python -m pytest tests -m codex_smoke -q` and the selected persistence smoke suite: 12 passed, 2 skipped (external DB configuration missing). The native process was actually started. `pre-commit run --all-files` passed, including dependency policy and secret scanning.

Reviewed the changed execution_control, mcp_bridge, runtime and regression files on 2026-10-15 for cancellation, shared confirmation, error redaction, ordinary-tool compatibility and per-turn isolation; no unresolved local blocker. Cloud acceptance and the new public image remain pending and must be recorded separately. Local fixture results do not establish cloud acceptance.
