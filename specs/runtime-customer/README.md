# Customer Runtime

[中文](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.zh.md)

Component: runtime-customer. Revised: 2026-10-20. Status: active.

Owns the public customer Agent execution boundary and composition of existing transport, dispatch, projection and durable store.

- CON-1: Server constructs CustomerRuntimeConfig with endpoint, engine_id, remote_app, SecretStr agent_config, CustomerSessionStore, declarative tools/skills and matching async executors. This object is not a request schema or a credential resolver. The Agent serializes neither this config nor its endpoint.
- CON-2: Agent(runtime="customer") bypasses local model setup; only local name/description/identity/memory/run processor plus runtime config are accepted. Native tools and tool callbacks require native_tools=True (CON-7); model/Agent callbacks, skills and other native configuration remain rejected. Execution revalidates clones/mutations.
- CON-3: Remote mapping is fixed by local app/user/session plus a digest binding endpoint, configuration and tool/skill revision. Private affinity is restored and durably updated before subsequent HTTP. Exact-session lookup does not read history into the model. A missing session after earlier execution blocks.
- CON-4: Reserve before remote effects, send only the new user Content (native media follows CON-8), bound preparation/run/cleanup, no turn retry. Completed local Events are journaled before streaming; final success requires terminal, ACK and cleanup. The next turn verifies ADK saved journal contents before releasing the pending display.
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

Defaults: total_timeout=165 seconds, operation_timeout=10 seconds, cleanup_timeout=10 seconds, max_concurrency=8, event_queue_size=16. The lease also covers bounded cleanup/store release. Shared requires sticky affinity after first-session preparation; native neither fabricates nor requires it. The first turn performs exact Session GET/create; continuations rely on the verified Host contract that rejects absent Sessions before reasoning, avoiding full history downloads. Changes to endpoint, Host config/environment, engine revision or tool/skill declarations require a new local Session. Rotating header values are excluded from that binding; keep their account/tenant ownership stable.

Call `await get_runtime("customer").recover_display(agent, adk_sessions, ("example_app", user_id, session_id))` only through trusted server code before another user turn if display persistence failed. It returns the number of appended events. Existing events must form the same journal prefix; conflicting content or later invocations block recovery. It does not resume an incomplete execution or release a crash-held owner. Recovery compares identity/content/actions/usage; ADK-generated node_info/output bookkeeping is excluded. Native tool state callbacks follow CON-7; plugins remain unsupported.

Runner compatibility: this stage verifies Google ADK Runner and the standard Harness HTTP routes. VeADK Runner.run() supplies max_llm_calls=100 by default; customer rejects that explicit local budget. Do not treat the convenience Runner.run() entry point as integrated until Host budget support or its caller adaptation is complete.

## Native tool integration

CON-7: native_tools=True connects declared async Agent.tools and native tool callbacks using detached serial state, trusted local event batches and the existing journal/recovery path. JSON session/temp: state only; temp: is not persisted. Other actions, toolsets and model/Agent callbacks remain rejected. Full boundaries and acceptance: [native tool design](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-tools/2026-10-20-customer-native-tools.md).

Native tool usage: construct CustomerRuntimeConfig with native_tools=True, matching CustomerTool declarations and executors={}; pass async Python functions, async FunctionTool/BaseTool instances and before_tool_callback/after_tool_callback/on_tool_error_callback to Agent. Matching ignores schema title/description annotations and normalizes absent object additionalProperties to False. Toolsets and synchronous functions are rejected before Host I/O. Host configuration and tool metadata remain server-owned. Increment engine_id/executor_revision when callback or implementation behavior changes.

Native calls are serial within a turn regardless of max_concurrency. Each has detached state; use ToolContext.state assignment/update to publish JSON deltas. Direct nested mutations without a delta are not committed. Only unprefixed session keys and temp: are supported; app:/user: writes and other nonempty actions (including skip_summarization) fail. temp: remains local to this invocation. Publication passes the same bounded queue and journal-before-yield path before returning to the Host; it does not acknowledge ADK persistence. Display parts for locally registered tools are validated but not displayed twice; Host-only tool display is preserved and never executed locally. State copy and serial execution have a cost; no performance improvement is claimed for this bridge. Tools/services/tracing are trusted caller-owned dependencies, not sandboxed code. Tool code must keep secrets out of results, state and telemetry. Existing shared/external side effects cannot be rolled back.


## Native protocol extension (2026-10-20)

Implemented and verified by targeted/full local regression. [Design and evidence](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-channel/2026-10-20-customer-native-channel.md) defines protocol="native" opt-in, /apps + /run_sse, exact result-echo ACK, multi-HTTP deadlines and binding isolation. Shared defaults remain unchanged. The channel validates and normalizes deferred calls/verified response echoes before existing display projection. Execution permits end before ACK waiting to avoid batch deadlock; deadlines and final-after-ACK remain. Store schema and incomplete-turn quarantine remain unchanged. No claim of full Skill/attachment support, crash recovery or production acceptance.

Use protocol="native" in CustomerRuntimeConfig for native Host. agent_config must be SecretStr(JSON AgentConfig); environment must be empty. The Host validates AgentConfig fields. native_tools=True independently enables local Agent.tools/callbacks for either protocol. Low-level users must keep reading events concurrently while awaiting submit_result ACK; CustomerToolDispatcher does this.


## Native attachment extension (2026-10-20)

SDK implementation, full regression and fixed Host source integration verified; fixed business artifact acceptance pending: [customer-native-attachments](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-attachments/2026-10-20-customer-native-attachments.md). Native input gains bounded original media and opaque metadata; Shared remains text-only. Runtime uses a separate 8 MiB native initial envelope; client max_initial_request_bytes=None inherits max_request_bytes. Tool batches remain 2 MiB and output events 1 MiB by default. Original input stays in ADK/Host history; journal/recovery schemas and output content are unchanged. The linked design owns exact limits and acceptance.

CON-8: Native accepts user Content only, up to 8 parts/3 inline blobs; PNG/JPEG/WebP/PDF, 4 MiB per blob, 5 MiB decoded total, 1 MiB total text and 7 MiB JSON message. Accept canonical standard/URL-safe Base64 and normalize to standard Base64; validate magic bytes and optional display_name (1–180 characters). Metadata is an opaque JSON object (16 KiB total, depth 8, 256 values per message). Accept snake/camel aliases without conflicts. Attachment-only input is valid; URI/fileData, thought/tool fields, unknown fields and invalid/empty payloads fail with unsupported_user_message before Host I/O. Shared remains text-only. Do not log or echo payloads in errors. No SDK PDF renderer: business Host owns conversion of model-request copies. Raw ADK user events retain original attachments; recovery journal still stores projected assistant/tool events only. Tests: tests/runtime/customer/test_native_attachments.py.


## Native stream timeout ownership (2026-10-21, SDK regression verified)

CON-4: Native body reading uses the channel single-turn deadline; operation_timeout bounds control operations and run response headers. See runtime-customer-channel CON-4/CON-6. Runtime defaults and outer total_timeout remain unchanged.

[Design / 设计](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-native-stream-timeout/2026-10-21-customer-native-stream-timeout.md)

## Display publication ordering (2026-10-21, proposed)

CON-4/CON-5: Runtime assigns new durable projected/native events local publication timestamps immediately before journal append/yield, strictly increasing at microsecond resolution after prior display history. This is not an executor-duration timestamp. Saved-prefix/content checks and old conflicted histories remain unchanged; recovery uses original journal timestamps and never replays tools. No schema, public signature, or configuration change. Acceptance is pending the real DatabaseSessionService regression and installed/Devbox verification in [customer-display-order](../../prd-spec/bugfixes/customer-display-order/2026-10-21-customer-display-order.md).
