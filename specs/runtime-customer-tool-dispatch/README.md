# runtime-customer-tool-dispatch

[Counterpart](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-tool-dispatch/README.zh.md)

ID: `runtime-customer-tool-dispatch`; revision: 2026-10-20; status: active.

Owns execution scheduling for validated Shared tool calls. It consumes [customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.md); it does not own endpoint/auth/session choice, model execution, ADK event conversion or persistence.

`CustomerToolDispatcher(client, request, executors, *, max_concurrency=8, event_queue_size=16, cleanup_timeout=10)` is an async context manager. Executors are an exact server-owned mapping of request tool names to async `(arguments, request_id)` functions. Use `async with ... as dispatch` and consume `dispatch.events()` once. The caller owns and closes the client; close the dispatcher before the client. No run may be restarted on the same dispatcher.

| ID | Contract |
| --- | --- |
| CON-1 | Snapshot request/executors; validate before HTTP. Only async executors, exact names. Execute at most max_concurrency (1–64); queue wait consumes deadline. |
| CON-2 | Receive and execute independently. Invalidate a cancelled call before task cancellation. Never submit a late/cancelled result or automatically retry. Tool exceptions expose only `tool_execution_failed`; deadline expiry aborts the run. |
| CON-3 | Observe validated Shared envelopes through a bounded queue (1–256, default 16). Overflow fails the run with `event_backpressure`. Observation is not authorization to execute again. |
| CON-4 | Terminal success follows successful completion of all still-required local result submissions. Explicit Host tool.cancel ends that call without requiring a result; late results are discarded. Errors take precedence over buffered events. No success on ambiguous ACK, timeout, cancellation or EOF. |
| CON-5 | Context exit revokes all submissions and requests cancellation once. Cleanup wait is positive/finite (default 10 seconds), covers owner and children; internal failure, context exit and repeated close share one deadline established by the first cleanup. `quiescent` is true only when all stopped. On cleanup_timeout quarantine the dispatcher/client and its execution context until quiescent. Executors must cooperate; no claim of forcibly stopping Python code. |
| CON-6 | No raw exception text, credentials, event payloads or tool results in diagnostics. Tasks inherit invocation context; the caller must supply trustworthy, revocable identity and persistent session exclusion. This API does not establish those guarantees. |

Verification: `tests/runtime/customer/test_dispatch.py` in the existing Harness release gate. [Design/evidence](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-tool-dispatch/2026-10-20-customer-tool-dispatch.md). Agent dispatch is integrated through CustomerRuntime; business adoption remains separate. Native integration follows runtime-customer CON-7 below.

## Usage

The trusted caller supplies client, request and executors; this does not create a local model.

```python
from veadk.runtime.customer import CustomerToolDispatcher

async def observe_run(client, request, executors):
    async with CustomerToolDispatcher(client, request, executors) as dispatch:
        async for event in dispatch.events():
            yield event
```

Consume observe_run with contextlib.aclosing so early exit also closes the dispatcher. After cleanup_timeout, use quiescent to quarantine execution context that has not stopped; never write forwarded events or task inputs to diagnostics.

Native Runtime integration: a private Python local-event batch shares the bounded dispatcher queue. It is never parsed from remote JSON. Native result submission waits for the Runtime journal/yield acknowledgement; cancellation, queue overflow and journal failure stop submission. Native mode validates remote display for locally registered tool names but emits the local completed call/response pair instead; Host-only tool display is preserved. Local state is governed by [runtime-customer CON-7](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.md). Existing explicit-executor display behavior is unchanged.


## Repeated cancellation cleanup (2026-10-20)

CON-5: Repeated caller cancellation must not skip the bounded join before client close. Defer cancellation propagation until the existing deadline or task completion; no deadline extension.

[Design](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-repeated-cancellation/2026-10-20-customer-repeated-cancellation.md)


## Native protocol extension (2026-10-20)

Implemented and verified by targeted/full local regression. [Design and evidence](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-channel/2026-10-20-customer-native-channel.md) defines protocol="native" opt-in, /apps + /run_sse, exact result-echo ACK, multi-HTTP deadlines and binding isolation. Shared defaults remain unchanged. The channel validates and normalizes deferred calls/verified response echoes before existing display projection. Execution permits end before ACK waiting to avoid batch deadlock; deadlines and final-after-ACK remain. Store schema and incomplete-turn quarantine remain unchanged. No claim of full Skill/attachment support, crash recovery or production acceptance.
