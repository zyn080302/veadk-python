# Native SSE body timeout correction

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/bugfixes/customer-native-stream-timeout/2026-10-21-customer-native-stream-timeout.zh.md)

Change ID: `customer-native-stream-timeout`; created/revised: 2026-10-21; status: approved (implementation/acceptance pending).

## Evidence and scope

`CustomerChannelClient` configures HTTPX with `operation_timeout`; native `_step` inherits it for response body reads. A real loopback reproduction with body delay 0.35 s, turn budget 2 s and operation budget 0.1 s fails around 0.178 s. Raising only the operation budget to 1 s succeeds. MockTransport does not enforce socket read timeouts. This defect is confirmed; whether it explains the downstream real-model failure remains unverified until a new installed artifact is tested.

Goal: allow a native model stream to wait within its complete turn budget. Non-goals: model retry, automatic run replay, new environment variables, Shared protocol changes, deployment or performance claims. Public signatures/defaults, identity, tools, ACK validation and persistence remain unchanged.

## Requirements and design

- FR-1: Given timely response headers, native first-body and inter-chunk waits longer than `operation_timeout` succeed within `turn_timeout`.
- FR-2: Connect, write, pool and response-header acquisition retain the short operation budget. Exact-session JSON control operations retain their entire short budget.
- FR-3: One existing turn deadline covers all native HTTP steps, local tool waits and downstream consumption. Timeout and caller cancellation close streams and settle dispatch tasks without replaying a run or result.
- FR-4: A delayed deferred-result echo must still match exactly before ACK; no success before verified final output. Error and timeout paths never synthesize success or usage.

For native `/run_sse` only, pass `httpx.Timeout(operation_timeout, read=None)` to `build_request`. The existing `fail_after(operation_timeout)` around `send(stream=True)` bounds response headers including partial headers. The existing outer turn scope bounds body reads. Setting `read=None` without that outer scope would be unsafe; this change is confined to `_NativeChannel._step`, which is owned by `_native_run`. Connection/write/pool deadlines remain finite. No automatic retries and no new tasks/state/storage. Short JSON and Shared requests are untouched. The alternative of increasing all operation timeouts would weaken control operations and still leave a hidden stream deadline.

Contract owner: [runtime-customer-channel](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-channel/README.md), CON-4/CON-6. Consumer: [runtime-customer](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer/README.md), CON-4, delegates native stream timeout semantics to that owner. No frontend, cloud, schema, permission or dependency changes. Tests use synthetic loopback HTTP only, no credentials, external calls or user state.

## Tasks and acceptance

| Requirement | Task | Acceptance | Verification |
| --- | --- | --- | --- |
| FR-1/FR-4 | T-1: add real HTTP regressions before code | AC-1: first-body, chunk gap and multi-step ACK cases fail before fix and pass after | `uv run --extra dev pytest tests/runtime/customer/test_native_stream_timeout.py` |
| FR-2/FR-3 | T-2: bound each timeout domain | AC-2: slow headers/control still fail; total deadline/cancel closes without replay | Same regression file, plus existing customer tests |
| FR-1–FR-4 | T-3: implement request timeout override | AC-3: customer/consumer contracts and release checks pass | `uv run --extra dev pytest tests/runtime/customer tests/test_harness_sidecar_release_gate.py` |
| FR-1–FR-4 | T-4: reconcile and verify | AC-4: full regression, pre-commit and artifact consumer validation recorded separately | `uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"`; `uv run --extra dev pre-commit run --all-files` |

The existing mandatory `.github/workflows/harness-sidecar-release-gate.yaml` already triggers on and runs all `tests/runtime/customer`; new regressions join that gate without a duplicated workflow. Wrappers use the existing repository environment with isolated HOME and loopback-only network, equivalent to the repository pytest entry point with explicit plugins.

## Review, authorization and delivery

Direct review (review-spec skill unavailable): requirements and bilingual contracts aligned; smallest affected request path; unchanged security and identities; total-deadline/cancellation/ACK/no-replay invariants retained; real socket tests cover the missing mechanism. No design blockers. User's active goal authorizes continued SDK/runtime correction and Devbox iteration; this is routine implementation within that scope, not a separately claimed design approval or release approval.

Verification on 2026-10-21: new regression on old code 4 failed / 3 passed (18.17 s); initial corrected suite 7 passed (11.32 s); full customer and release-gate contracts 349 passed (28.10 s), including 10 new real HTTP cases. Full regression with 2 workers: 7909 passed, 50 skipped, 4 xfailed, 6 subtests passed (444.21 s); skips do not prove capability. All five pre-commit hooks pass; bilingual identifiers, links and whitespace pass. Tested df31f1ce plus this design diff; implementation SHA256 fde11b8a480995aa6bae5b740d35b246d168320db21e6045684b4f946c2e9d99, regression SHA256 4ddd1537bfd5ae8adc72b58bd9d9c45b52d1da49a6750e83ee411ff75e926645; sources unchanged during full regression. T-1/T-2/T-3 and AC-1/AC-2/AC-3 complete. Installed artifact and Devbox business checks in T-4/AC-4 remain not_run; delivery is incomplete. Artifact/Devbox validation remains separate and required before claiming the business failure fixed. Risk: an idle body now holds a connection until the existing turn deadline, intentionally bounded; changing Host behavior or full business quality is outside this SDK fix and remains in the overall optimization goal.
