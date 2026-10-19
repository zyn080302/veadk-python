# Customer Runtime

[中文](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.zh.md)

Component: runtime-customer. Revised: 2026-10-20. Status: active.

Owns the public customer Agent execution boundary and composition of existing transport, dispatch, projection and durable store.

- CON-1: Server constructs CustomerRuntimeConfig with endpoint, engine_id, remote_app, SecretStr agent_config, CustomerSessionStore, declarative tools/skills and matching async executors. This object is not a request schema or a credential resolver. The Agent serializes neither this config nor its endpoint.
- CON-2: Agent(runtime="customer") bypasses local model setup; only local name/description/identity/memory/run processor plus runtime config are accepted. Native tools and tool callbacks require native_tools=True (CON-7); model/Agent callbacks, skills and other native configuration remain rejected. Execution revalidates clones/mutations.
- CON-3: Remote mapping is fixed by local app/user/session plus a digest binding endpoint, configuration and tool/skill revision. Private affinity is restored and durably updated before subsequent HTTP. Exact-session lookup does not read history into the model. A missing session after earlier execution blocks.
- CON-4: Reserve before remote effects, send only new text, bound preparation/run/cleanup, no turn retry. Completed local Events are journaled before streaming; final success requires terminal, ACK and cleanup. The next turn verifies ADK saved journal contents before releasing the pending display.
- CON-5: recover_display(agent, session_service, local_identity) obtains the same lease, checks saved prefix/content, appends missing display and reads it back; no remote calls or tool replay. Uncertain execution, conflicting/reordered history and abandoned owners require separate recovery.
- CON-6: HarnessApp accepts a prebuilt customer Agent. Request overrides may only reaffirm runtime="customer"; endpoint/config/engine/model/tool switching is not allowed. HarnessConfig/environment creation remains adk/codex. Explicit max_llm_calls and unsupported plugins/features are rejected; Host loop/token budgets are still a separate obligation.

Identity must already be authenticated upstream. Headers come from a server callback, never arbitrary client forwarding. Store encryption/access/timeouts and trusted executor result handling belong to the caller. SQLite/offline Host tests do not prove PostgreSQL or deployed Host compatibility. Errors use fixed codes; cancellation propagates. No automatic lease takeover, distributed exactly-once, credential body filtering, or noncooperative tool termination.

Design/tasks/verification: [change record](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/runtime-customer/2026-10-20-customer-runtime.md). Tests: tests/runtime/customer/test_runtime.py, existing customer and Harness gates. No new dependencies, frontend, deployment or CLI factory.


## Server integration example

Use the current SDK branch in an async application factory. The endpoint and full Host configuration must already have been obtained by trusted local configuration code; do not put them in request JSON. `host_configuration` below is a `SecretStr`, not a YAML filename.

```python
from veadk import Agent
from veadk.cloud.harness_app.app import HarnessApp
from veadk.memory.short_term_memory import ShortTermMemory
from veadk.runtime.customer import CustomerRuntimeConfig, CustomerSessionStore

# db_engine: caller-owned AsyncEngine with hide_parameters=True and safe logs.
# adk_sessions: caller-owned ADK SessionService for display persistence.
store = CustomerSessionStore(db_engine)
await store.initialize()
config = CustomerRuntimeConfig(
    endpoint=customer_endpoint,
    engine_id="customer-v1",
    remote_app="managed_example",
    agent_config=host_configuration,
    store=store,
    headers=trusted_headers_provider,
    tools=tool_declarations,
    executors=async_executors,
)
agent = Agent(
    name="customer_agent",
    runtime="customer",
    customer_runtime_config=config,
)
app = HarnessApp(
    agent, ShortTermMemory(session_service=adk_sessions), "example_app"
).app
```

No `Agent.tools`/model callback bridge is installed by this example. Supply matching async executors explicitly; the caller owns authentication and result filtering. Do not set local `max_llm_calls`, model fields, plugins or request overrides; this stage cannot enforce those on the Host. The standard `/run` and `/run_sse` routes are supported for text input. Application authentication and deployment are outside this example.

Defaults: total_timeout=165 seconds, operation_timeout=10 seconds, cleanup_timeout=10 seconds, max_concurrency=8, event_queue_size=16. The lease also covers bounded cleanup/store release. A sticky affinity value is required after first-session preparation. The first turn performs exact Session GET/create; continuations rely on the verified Host contract that rejects absent Sessions before reasoning, avoiding full history downloads. Changes to endpoint, Host config/environment, engine revision or tool/skill declarations require a new local Session. Rotating header values are excluded from that binding; keep their account/tenant ownership stable.

Call `await get_runtime("customer").recover_display(agent, adk_sessions, ("example_app", user_id, session_id))` only through trusted server code before another user turn if display persistence failed. It returns the number of appended events. Existing events must form the same journal prefix; conflicting content or later invocations block recovery. It does not resume an incomplete execution or release a crash-held owner. Recovery compares identity/content/actions/usage; ADK-generated node_info/output bookkeeping is excluded. Native tool state callbacks follow CON-7; plugins remain unsupported.

Runner compatibility: this stage verifies Google ADK Runner and the standard Harness HTTP routes. VeADK Runner.run() supplies max_llm_calls=100 by default; customer rejects that explicit local budget. Do not treat the convenience Runner.run() entry point as integrated until Host budget support or its caller adaptation is complete.

## Native tool integration

CON-7: native_tools=True connects declared async Agent.tools and native tool callbacks using detached serial state, trusted local event batches and the existing journal/recovery path. JSON session/temp: state only; temp: is not persisted. Other actions, toolsets and model/Agent callbacks remain rejected. Full boundaries and acceptance: [native tool design](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-tools/2026-10-20-customer-native-tools.md).

Native tool usage: construct CustomerRuntimeConfig with native_tools=True, matching CustomerTool declarations and executors={}; pass async Python functions, async FunctionTool/BaseTool instances and before_tool_callback/after_tool_callback/on_tool_error_callback to Agent. Matching ignores schema title/description annotations and normalizes absent object additionalProperties to False. Toolsets and synchronous functions are rejected before Host I/O. Host configuration and tool metadata remain server-owned. Increment engine_id/executor_revision when callback or implementation behavior changes.

Native calls are serial within a turn regardless of max_concurrency. Each has detached state; use ToolContext.state assignment/update to publish JSON deltas. Direct nested mutations without a delta are not committed. Only unprefixed session keys and temp: are supported; app:/user: writes and other nonempty actions (including skip_summarization) fail. temp: remains local to this invocation. Publication passes the same bounded queue and journal-before-yield path before returning to the Host; it does not acknowledge ADK persistence. Display parts for locally registered tools are validated but not displayed twice; Host-only tool display is preserved and never executed locally. State copy and serial execution have a cost; no performance improvement is claimed for this bridge. Tools/services/tracing are trusted caller-owned dependencies, not sandboxed code. Tool code must keep secrets out of results, state and telemetry. Existing shared/external side effects cannot be rolled back.
