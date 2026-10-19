# Customer channel to ADK event stream

[中文版](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/prd-spec/features/customer-adk-events/2026-10-20-customer-adk-events.zh.md)

Change ID: `customer-adk-events`; created/revised: 2026-10-20; status: implemented.
Component: [runtime-customer-adk-events](/Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/specs/runtime-customer-adk-events/README.md).
Predecessor: `customer-tool-dispatch`.

## Evidence, goals and scope

The retained customer Host calls `run_studio_agent(..., yield_user_message=True)` and forwards native ADK `Event.model_dump(mode="json", by_alias=True, exclude_none=True)`. The local ADK Runner already saves the input and saves non-partial output before yielding it. Forwarding remote Events directly would duplicate input and accept remote state changes, identity and workflow controls. ADK `is_final_response()` can return true before the Shared success terminal and before local tool ACKs finish.

Add an independently usable public `CustomerAdkEventStream` over the existing dispatcher. It projects ordinary single-agent text/tool runs into safe display Events and owns the dispatcher context. This is a stage of the approved integration blueprint, not a completed customer Runtime. Agent runtime/config dispatch, durable session mapping/leases, ADK tool callbacks, trusted business identity, shared quotas, attachments, interactive auth/confirmation and multi-agent workflows remain required follow-up work. No model loop, tool executor or persistence implementation is copied.

## Requirements and scenarios

| ID | Observable requirement |
| --- | --- |
| FR-1 | Explicit local author/invocation/branch and a snapshot of the new text user message; no ambient credentials or remote identity trusted. An exact initial user echo is omitted; any additional/different/late user event fails. |
| FR-2 | Reconstruct only text/thought, complete function calls/responses and bounded numeric usage. Ignore remote actions, state, metadata, IDs, timestamps and routing. Reject unsupported content instead of silently losing it. |
| FR-3 | Remote tool display IDs pair only by exact remote function ID and name, and are replaced with fresh local IDs. Never infer relation to channel request_id; never execute a display event. Reject duplicate calls/responses, orphans, partial tool fragments and unresolved calls at success. |
| FR-4 | Forward partial text promptly. Hold one complete final answer until a successful dispatcher terminal and successful dispatcher cleanup. Error, cancellation, EOF, failed ACK or cleanup must not yield a final answer. Missing/multiple final answers fail explicitly. |
| FR-5 | Own one invocation/consumer. Caller must use async context management, including on consumer/persistence failure; close the stream then dispatcher in the same task. No replay or automatic retries. Reuse needs a fresh adapter and dispatcher. |
| FR-6 | Bound each raw event to 1 MiB, events to 4096, display calls to 1024 and pending calls to 64; fixed diagnostics only. Native usage on non-partial events is copied once; partial usage is omitted. |

## Design and tasks

Use composition, following the already selected python-design-patterns skill. Public stream owns lifecycle and terminal ordering; a private synchronous projector owns field selection and within-run display correlation. No additional background worker or queue is introduced: dispatcher remains the only pump. Content/usage are validated locally without exposing Pydantic inputs. Local trusted callback actions will require a separate path in the future Runtime; remote state is owned by the Host.

| Task | Files / requirement | Acceptance |
| --- | --- | --- |
| T-1 | Add tests first under `tests/runtime/customer/test_events.py`; FR-1–FR-6 | AC-1 missing public API fails, then projection/trust/limits pass |
| T-2 | Add `veadk/runtime/customer/events.py` and public export; FR-1–FR-6 | AC-2 real dispatcher round trip emits one final only after ACK and cleanup |
| T-3 | Exercise actual ADK Runner/SessionService with a local test agent; FR-1, FR-4, FR-5 | AC-3 one user event, isolated local state, correct tool display, persistence failure closes without repeating execution |
| T-4 | Original hooks, SDK regression, bilingual/link checks, business navigation/evidence | AC-4 verified stage pushed to independent branches; no deployment claim |

Targeted command: `python3 .codex/run_offline_tests.py tests/runtime/customer`; full SDK: `python3 .codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke'`. Local wrapper isolates HOME/dotenv/telemetry/network; CI already runs `python -m pytest -q tests/runtime/customer` in the Harness gate. Original pre-commit hooks remain mandatory. No dependencies, existing runtime selection, frontend, default business entrypoint or wheel changes.

## Review, approval, risks and verification

Direct design review completed before production/tests; review-spec is unavailable. Reviewed protocol/ADK feasibility, identity/state ownership, duplicate and terminal behavior, bounded resources, cancellation, error redaction and bilingual equivalence. User's existing instruction to implement the blueprint and immediately push verified stages authorizes this stage; no further approval or deployment is inferred. Main remaining integration risks are Host event shape variation, durable recovery and callback semantics. Unsupported capabilities fail and are not advertised as migrated.

2026-10-20, base 89748f19 plus this change: AC-1–AC-3 pass. Missing public API failed before implementation. Review added three failing regressions for malformed role list/dict (TypeError) and empty user content wrongly accepted as an answer; strict role validation now rejects all three with a fixed code. Final targeted customer checks: 166 passed (6.28 s); events combined statement/branch coverage 97%, all customer 91%. Real loopback HTTP and actual ADK Runner/SessionService persistence and failure cleanup pass. All five original pre-commit hooks, staged credential scan, Python 3.10 grammar and bilingual identifiers/8 absolute links pass. Source is unchanged after these gates. Final full SDK regression: 7699 passed / 50 skipped / 4 xfailed / 6 subtests passed (423.75 s, 2 workers). AC-4 code/document gates pass; independent-branch push and remote hash verification are recorded in the consuming business repository evidence as the final delivery action.

The actual Runner integration uses a test BaseAgent that owns the new stream. It does not prove the production Agent delegate or HarnessApp path is wired; that remains the next Runtime stage. Real customer Runtime, model/MCP, 20-question evaluation and remote CI: `not_run`; this stage uses offline fixtures and loopback only. Keep overall P0–P4 active.
