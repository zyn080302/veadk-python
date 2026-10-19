# Close delegated Runtime streams inside their owning task

[Chinese](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/runtime-stream-cleanup/2026-10-20-runtime-stream-cleanup.zh.md)

Change ID: `runtime-stream-cleanup`. Created/revised: 2026-10-20. Status: implemented.
Contract: [runtime-stream-lifecycle](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-stream-lifecycle/README.md).

## Evidence, scope and scenarios

`Agent._run_async_impl` explicitly closes the ADK generator but forwards external Runtime events with a bare `async for`. Closing that wrapper while suspended at `yield` does not synchronously close the delegated generator. This is a general ownership defect: a Runner persistence failure, early consumer exit or cancellation during event processing can leave Runtime cleanup to asynchronous finalization in a different task. Customer event streams require exit in the task that entered them.

This stage fixes the shared Agent boundary before customer Runtime registration. It does not register customer, add session mapping, change model retry policy, or claim a deployed end-to-end migration. Those remain in the authorized integration blueprint.

Given a delegated Runtime has yielded an event, when the consumer closes its iterator, then Runtime cleanup completes in the entering task before the close returns. Given Runner persistence fails after a tool result, then the existing error propagates, the delegated stream closes, and no tool is replayed. Cancellation and normal completion retain their meanings.

## Requirements and implementation

| Requirement | Task | Acceptance |
| --- | --- | --- |
| FR-1: own the delegated generator with `aclosing` | T-1: failing regression then minimal change to `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/agent.py` | AC-1: explicit close, consumer error and cancellation run cleanup once in the original task |
| FR-2: retain native event order, output state and errors | T-2: real Agent/Runner tests and Harness HTTP regression | AC-2: normal completion and failure preserve results, state and error behavior |
| FR-3: release real customer dispatcher resources through this boundary | T-3: compose the existing client/dispatcher/events with a test Runtime; use the production Agent | AC-3: save failure closes HTTP, cancels the run, stops owned tools and never replays them |
| FR-4: retain the regression in required gates | T-4: extend `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.github/workflows/harness-sidecar-release-gate.yaml` and its contract test | AC-4: source/test changes trigger the gate and execute the regression |

Use the existing `contextlib.aclosing`, with no dependency or wrapper abstraction. Do not swallow cleanup failures or translate cancellation into successful final output. The Runtime remains responsible for its own bounded cleanup; Agent does not forcibly stop non-cooperative Python tools. Tests use synthetic configuration, isolated HOME and local transports. No credentials or real service calls are needed.

Affected consumers: every non-ADK Runtime reached through Agent, including cloned Harness Agents. Public signatures, Runtime selection, model configuration and wire formats stay unchanged. A new focused lifecycle spec owns the changed resource-release contract; existing customer protocol contracts are referenced, not duplicated. Studio frontend and dependencies are unaffected.

## Review and authorization

Direct design review before production/test changes (`review-spec` is unavailable): ownership, exception propagation, same-task cleanup, compatibility and bilingual equivalence reviewed. No design blocker. User authorization is the existing instruction to implement the integration blueprint and continue optimization, plus the explicit request to commit/push each verified stage to independent branches. This stage is a prerequisite fix within that scope; no merge or deployment is authorized.

## Verification record

2026-10-20, diff based on `37902a4b24eba648d9a160b3dcdb61c84c396ac5`:

- `pass`: initial Agent regression reproduced 11 failures / 4 passes; restoring the original Runner with corrected child-task ownership assertions reproduced all 5 Runner regressions. Fixed lifecycle tests: 28 passed in 5.77 seconds, including real loopback HTTP disconnect and resend. Earlier affected suite: 213 passed in 20.56 seconds.
- `pass`: `python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`: 7727 passed, 50 skipped, 4 xfailed, 6 subtests passed in 390.11 seconds, 2 workers. Explicit Codex/Pi smoke was excluded. Original pre-commit: all 5 checks passed. Python 3.10 syntax, paired contract IDs, 8 absolute links and diff whitespace passed.
- `not_run`: remote customer, models/MCP, original customer 20 questions; this change does not provide their required integration environment.
- `not_applicable`: new dependency resolution, frontend build or diagram changes.

The isolated local test wrapper is local development infrastructure; CI runs the same committed tests with repository dependencies. The test entry is `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/tests/runtime/test_runtime_stream_cleanup.py`; all in-scope AC-1–AC-4 are verified locally. Remote CI, deployment, customer registration and business wheel replacement remain unverified or not implemented; they are not inferred from these results.

## Reviewed scope clarification: Runner forwarding

The standard Harness uses `veadk.runner.Runner`, whose `intercept_new_message` and `run()` forwarding generators also use bare `async for`. AC-1 and AC-2 therefore include these SDK-owned wrappers, not only Agent. Extend T-1 to `/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/veadk/runner.py`, use `aclosing` at each owned boundary, and test the public `run_async`, processor early exit/error in `run`, and Harness HTTP storage failure. Third-party processors still own their internal generators. This is the same cleanup mechanism along the required chain, with no change to logging or successful-run post-processing. Direct review completed before extending tests/implementation; no new permission or deployment scope.
