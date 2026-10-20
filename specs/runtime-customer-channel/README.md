# runtime-customer-channel

[Counterpart](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.zh.md)

ID: `runtime-customer-channel`; revision: 2026-10-20; status: active.

This component owns the public client for customer Shared and native HTTP protocols. It does not execute tools, create a second model loop, or select a business identity. Callers use `CustomerChannelClient` as an async context manager, probe `capabilities()`, explicitly `create_session(app_name, user_id, session_id)`, and enter `run(CustomerRunRequest)` to consume `events()` and `submit_result()`. Use one client per trusted business session; reuse its HTTP pool and affinity for continuation. `Agent(runtime="customer")` is implemented by the higher-level CustomerRuntime composing this client. The table and example describe the default Shared protocol; native differences are specified in the extension below.

| ID | Area | Contract |
| --- | --- | --- |
| CON-1 | Protocol | `studio-tool-channel/1`; `/managed/harness/studio-channel/v1/{capabilities,http-runs}`; `/managed/harness/studio-channel/v1/http-channels/{channel_id}/messages`; `/managed/apps/{app}/users/{user}/sessions`. Session create uses `sessionId`; run payload uses `session_id`. |
| CON-2 | Snapshot | `CustomerTool` includes explicit source `mcp/studio/knowledgebase`; default timeout 600000 ms, max 1800000 ms; digest uses sorted complete manifests, excludes nulls. At most 64 tools and 16 skills. `CustomerSkill` includes instructions/references/assets; scripts must be empty. `CustomerRunRequest` adds full secret `agent_config` and `environment`, fresh run/channel/scope, one new user message. No history replay or environment context. |
| CON-3 | Lifetime | One client binds to one (app,user,session); one live run. Control operations cannot race with runs or other control operations. Caller owns persistence and closes the client. Successful `run.completed` permits success only without preceding error events or pending tool results; error/cancelled/EOF/malformed events raise `CustomerChannelError` with a fixed code. Local mapping and HTTP state never imply remote persistence. |
| CON-4 | HTTP | Trusted HTTP(S) endpoint with no userinfo/query/fragment; plain HTTP only for loopback tests. Explicit headers provider, no ambient proxies or redirects. `X-Session-Id` is private opaque affinity updated from valid responses; never placed in events or state. Operation timeout 30 s, turn timeout 165 s, cleanup timeout 5 s; positive finite configurable limits. HTTP bodies/events capped at 1 MiB and run payload at 2 MiB by default. No retries, including ambiguous tool-result failure. |
| CON-5 | Tools | `tool.call` validates run/scope/catalog/name/executor/schema/deadline before exposure. At most 64 pending calls and 1024 distinct calls per run. Duplicate IDs fail; tool.cancel invalidates pending submission. A result is consumed before HTTP so cancellation or delivery failure cannot replay it. Execution cancellation is the later adapter owner; transport emits tool.cancel. |
| CON-6 | Cleanup | Context exit before a terminal attempts run.cancel once within cleanup timeout, then closes the response even if cancellation fails. Cleanup leaf tasks are bounded; no unbounded queues are created. Normal completion performs no cancel. Entire run budget includes downstream consumption. Cancellation exceptions retain cancellation semantics. |
| CON-7 | Compatibility | Independent of ordinary Studio manifests. Existing dispatch, App, defaults, callback behavior and dependencies are unchanged. Public client configuration must not be filled from untrusted request headers. Secrets and remote bodies never appear in diagnostic exceptions. Tests use synthetic configuration and HTTP substitutes; real endpoint acceptance remains separate. |

Verification: `tests/runtime/customer/` → CON-1–CON-7; `.github/workflows/harness-sidecar-release-gate.yaml` runs the same contract suite.

Design and evidence: [customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-channel/2026-10-20-customer-channel.md).

```python
from pydantic import SecretStr
from veadk.runtime.customer import CustomerChannelClient, CustomerRunRequest

async def invoke(endpoint, header_provider, full_config: SecretStr, user_id, session_id):
    async with CustomerChannelClient(endpoint, headers=header_provider) as client:
        await client.capabilities()
        await client.create_session("managed_example", user_id, session_id)
        request = CustomerRunRequest(
            app_name="managed_example", user_id=user_id, session_id=session_id,
            agent_config=full_config,
            new_message={"role": "user", "parts": [{"text": "Hello"}]},
        )
        async with client.run(request) as channel:
            async for event in channel.events():
                # Forward validated events to the owning adapter, without logging payloads.
                yield event
```

The caller supplies a complete Host-supported configuration and an authorized endpoint; this snippet does not configure or call a model on its own. Call session creation only for a new session. For continuation, reuse the client and session but construct a new CustomerRunRequest. Supply tools/skills explicitly; concurrent tool execution and cancellation are the adapter's responsibility. Never log the request or event payload. To reproduce local offline evidence use the command in the linked PRD; CI runs `python -m pytest -q tests/runtime/customer` in its isolated fixture environment.


## Durable Runtime integration additions (2026-10-20)

`restore_session(app_name, user_id, session_id, affinity=SecretStr(...))` binds a fresh client once before HTTP. `session_exists(...)` checks that exact remote session and returns only a boolean; only HTTP 404 means missing. It never lists sessions or returns history. Constructor `on_affinity` is an optional async callback: new private affinity is persisted before it replaces the current value or later requests can construct their headers. Callback failure poisons the client with `affinity_persistence_failed`; cancellation still propagates. `aclose()` discards callback and private data. These are additive; existing clients need not supply durable storage.


## Repeated cancellation cleanup (2026-10-20)

CON-6: Run cancellation, response close and pool close use bounded owned leaf tasks to withstand repeated direct cancellation. No unbounded queues; original generators and AnyIO scopes remain in their owning task. Caller cancellation still propagates after cleanup.

[Design](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-repeated-cancellation/2026-10-20-customer-repeated-cancellation.md)


## Native protocol extension (2026-10-20)

Implemented and verified by targeted/full local regression. [Design and evidence](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-channel/2026-10-20-customer-native-channel.md) defines protocol="native" opt-in, /apps + /run_sse, exact result-echo ACK, multi-HTTP deadlines and binding isolation. Shared defaults remain unchanged. The channel validates and normalizes deferred calls/verified response echoes before existing display projection. Execution permits end before ACK waiting to avoid batch deadlock; deadlines and final-after-ACK remain. Store schema and incomplete-turn quarantine remain unchanged. No claim of full Skill/attachment support, crash recovery or production acceptance.


## Native attachment extension (2026-10-20)

SDK implementation, full regression and fixed Host source integration verified; fixed business artifact acceptance pending: [customer-native-attachments](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-attachments/2026-10-20-customer-native-attachments.md). Native input gains bounded original media and opaque metadata; Shared remains text-only. Runtime uses a separate 8 MiB native initial envelope; client max_initial_request_bytes=None inherits max_request_bytes. Tool batches remain 2 MiB and output events 1 MiB by default. Original input stays in ADK/Host history; journal/recovery schemas and output content are unchanged. The linked design owns exact limits and acceptance.
