# Customer native tool bridge

[中文](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-native-tools/2026-10-20-customer-native-tools.zh.md)

Change ID: customer-native-tools. Created/revised: 2026-10-20. Status: implemented.
Component: [runtime-customer](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.md).

## Background and scope

Customer Runtime currently accepts only explicit async executors and rejects Agent.tools and tool callbacks. SkyEyes needs its existing Python MCP functions and ToolContext identity preserved. ADK 2.7.1 functions.handle_function_calls_async executes native before/after/on_error callbacks; State.__setitem__ also mutates its backing dictionary before SessionService persistence. Sharing the original invocation state with late tasks is unsafe.

This increment connects async FunctionTool/BaseTool and Python async functions plus native tool callbacks to the actual customer Runtime. Model/Agent callbacks, SkillToolset resolution, artifacts, interactive auth/confirmation, plugins, multi-agent and production deployment remain subsequent blueprint work; they continue to fail explicitly. This is an increment toward the already authorized blueprint, not completion of the migration.

## Requirements and scenarios

- FR-1: With server-owned native_tools=True, Agent.tools must match the configured declarations by name/schema. No explicit executors may coexist. Reject mismatches, duplicate names, synchronous functions, deferred/long-running tools and toolsets before Host I/O. Existing explicit-executor mode stays compatible.
- FR-2: Given a valid reverse tool.call, use the current local ToolContext identity and inherited ContextVars; run ADK native before/after/on_error callbacks exactly once. Forward the structured response without string coercion. Never execute display events.
- FR-3: Native calls within an invocation run serially, each on a detached session state snapshot. Only successful supported state deltas become visible to the next call after local journaling. Completed calls produce local call/response Events through the Runtime's existing journal-before-yield path. Remote display for locally registered tool names is validated but suppressed in native mode; Host-only tools and unrelated model text/usage remain.
- FR-4: Only JSON session state and temp: state are supported. temp: values are invocation-local and excluded from persisted actions; app:/user: writes, non-JSON state and other nonempty actions fail closed. Unsupported local actions must not become a successful Host result or local final answer. No claim of cross-session transactional state.
- FR-5: Cancellation, deadlines, backpressure, journaling failure and cleanup failure revoke local result submission. Late tool mutation must not affect the original session or subsequent tools. Unhandled tool exceptions have a fixed tool_execution_failed result; recovered errors use the native callback result. No error body logging. External side effects of noncooperative tools cannot be rolled back.
- FR-6: The complete native tool events remain recoverable with existing completed-turn display recovery; no HTTP or tool replay. Next-turn read-back remains necessary because a resumed generator is not proof of ADK persistence.

## Design and alternatives

Add keyword-only native_tools=False to CustomerRuntimeConfig, include the mode in the session binding, and allow tools/before_tool_callback/after_tool_callback/on_tool_error_callback only in that mode. Keep explicit CustomerTool metadata (revision, timeout, risk) server-owned. Compare ADK declarations using its existing schema conversion, ignoring schema title/description annotations and normalizing an absent object additionalProperties to False. Operators must increment engine/executor revisions when implementation or callbacks change; code bodies cannot be fingerprinted reliably.

An invocation-local bridge owns the serial lock and state copy. Each call clones invocation/session data, invokes ADK functions, validates raw JSON state and supported actions before serialization, and sends a private Python event batch to the dispatcher. The same bounded dispatcher queue carries remote envelopes and local batches. Projection yields local Events to Runtime; its acknowledgement means the entire batch passed the journal/yield path, not that ADK storage committed. The bridge then updates its detached state and returns the Host payload. The result status is retained separately from its JSON content. Cancelled request IDs and runtime closure are checked before enqueuing and after acknowledgement. The final answer still requires tool result ACKs and cleanup.

Rejecting all callbacks would lose business behavior; emitting events from executor tasks directly to the journal would break ordering. The chosen queue reuses one owner. Serial execution trades per-invocation tool parallelism for deterministic read/modify/write state; explicit async executor mode keeps its existing concurrency. Services and arbitrary trusted tool code retain caller ownership; this bridge is not a Python sandbox.

## Tasks and acceptance

| Requirement | Task | Acceptance | Verification |
| --- | --- | --- | --- |
| FR-1/2 | T-1 config and native_tools.py | AC-1 actual Agent/Runner executes native callbacks and rejects invalid catalogs before HTTP | customer native integration tests |
| FR-3/4 | T-2 dispatch/events/runtime integration | AC-2 parallel arrivals see serialized state, no duplicate display or remote actions; unsupported actions fail | native integration and existing projection/dispatcher tests |
| FR-5 | T-3 lifecycle regressions | AC-3 cancellation, late mutation, bounded queues and journal failure cannot publish success | native/dispatcher/runtime tests |
| FR-6 | T-4 persistence and Harness verification | AC-4 actual /run and /run_sse, next turn and recovery preserve local actions without replay | loopback HTTP and Runner integration |
| all | T-5 docs, review and delivery | AC-5 bilingual contracts, full Python regression, pre-commit; commit/push authorized independent branch | repository gates |

Affected: veadk/runtime/customer/{config,dispatch,events,runtime,native_tools}.py, tests/runtime/customer/, this PRD and component spec. Existing Harness release gate already discovers all customer tests. No dependency, frontend, schema migration or wire protocol changes.

## Review and approval

2026-10-20 direct review (review-spec unavailable): checked contracts, errors, trust boundaries, bounded lifecycle, compatibility and bilingual equivalence. Resolved the backing-state mutation risk with detached copies; resolved uncorrelated remote/local function IDs by keeping only local tool display; excluded temp: from journal to match ADK persistence. No open design blocker. User's existing execution-blueprint authorization and latest stage commit/push instruction cover this increment; no additional permission is inferred from repository files.

## Verification and delivery

Executed on 2026-10-20 against parent 896802b44747d759b3ea8dbe8f50890fa5cc041c plus this change’s five customer implementation files and native tests. Commands: python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py tests/runtime/customer; then the same wrapper -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'; isolated pre-commit run --all-files after remote synchronization. Only synthetic local HTTP fixtures are authorized here. Real Host/model/MCP, customer 20 questions, PostgreSQL and deployment are not_run; this increment cannot establish live compatibility or performance gains.

Final review addition: ADK extracts image/media tool results into FunctionResponse.parts before JSON normalization. A regression reproduced a silently dropped image (DID NOT RAISE); the bridge now rejects media/extra response fields before emitting local Events or a Host result. This enforces the existing no-attachments boundary. Unknown reverse tool names are still rejected by the channel; on_tool_error handles registered tool execution failures, not Host-side unknown-name recovery. Existing positional CustomerRuntimeConfig arguments are preserved.

Review refinement before implementation: a new failing test showed that globally hiding remote tool display also hid Host-only read_skill activity. Suppression must apply only to locally registered tool names. Host-only tool display retains the existing projection validation and never causes local execution. This preserves the established remote Skill snapshot behavior; it does not add local SkillToolset support. The superseded second broad run was stopped; the final gates below cover this refined implementation.


Final verification (2026-10-20):

- **pass**: the final full Python regression through the isolated wrapper, 2 workers: 7,824 passed, 50 skipped, 4 xfailed, 6 subtests passed in 379.03 seconds. Smoke markers were excluded as specified; skips/xfails are not acceptance of their paths.
- **pass**: 94 final native-tool/event tests in 9.70 seconds, including actual loopback `/run` and `/run_sse`, Session read-back and a second turn; Host and tools use synthetic fixtures. An earlier related suite had 310 passes before the final media/display refinements.
- **fail before / pass after**: initial 10 new tests rejected unsupported native_tools on the parent revision; media-loss and Host-only display regressions separately reproduced failures before correction. There are 21 added test cases in the final change.
- **pass**: 24 absolute document links, paired requirement/task/acceptance identifiers, and Python 3.10 syntax for all six changed Python files. Existing Harness gate collects the new test file.
- **pass**: the original five-hook pre-commit gate after remote synchronization and final documentation reconciliation (Ruff check/format, hardcoded secret scan, dependency policy and YAML secret scan).
- **not_run**: live Host/model/MCP, customer 20 questions, PostgreSQL, wheel/image, remote CI and deployment. This stage establishes local SDK integration only; no claim of performance improvement or completed business migration.

T-1–T-4 and AC-1–AC-4 are implemented and verified within this scope. T-5/AC-5 delivery uses the authorized user fork branch; push verification is recorded in the business evidence with the resulting SDK commit.
