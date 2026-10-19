# Agent Runtime stream lifecycle

[Chinese](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-stream-lifecycle/README.zh.md)

Component: `runtime-stream-lifecycle`. Revised: 2026-10-20. Status: active (implemented and locally verified).
Owner: `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/agent.py`, external `BaseRuntime.run_async` boundary.
Design and verification: [runtime-stream-cleanup](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/runtime-stream-cleanup/2026-10-20-runtime-stream-cleanup.md).

- CON-1: Agent owns the delegated asynchronous generator for the lifetime of its `_run_async_impl`. Normal exhaustion, explicit close and exception unwinding close it in the same task; no detached finalizer is used for this boundary.
- CON-2: yield native events in order, applying the existing output-state behavior. Do not replay invocation or tools when persistence/consumption fails. Preserve errors and cancellation; cleanup failures remain visible.
- CON-3: callers must exhaust or explicitly close their iterator; a bare `break` is not a close. Runtimes own cancellation, deadlines, protocol terminals and their children's cleanup. This boundary does not implement forceful tool termination, persistence recovery or request deduplication.

There is no new state store, identity field, configuration, permission or dependency. Resource ownership is per invocation, including Harness clones; the cached Runtime object remains reusable. Public API and ADK behavior are unchanged. Tests cover direct Agent delegation, real Runner storage failure and local Harness HTTP. Local customer tests exercise the existing dispatcher through a test Runtime; they do not establish public customer Runtime registration or production connectivity.

Verification: `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/test_runtime_stream_cleanup.py`, customer tests and the Harness sidecar release gate. CON-1–CON-3 map to the design's AC-1–AC-4. No remote credentials or services are required for these regressions.

CON-1 and CON-2 also apply to SDK-owned `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runner.py` forwarding in `intercept_new_message` and `run()`. Processor-owned wrappers must close their own children. Tests include public VeADK Runner methods and standard Harness HTTP. Successful post-processing behavior remains unchanged.
