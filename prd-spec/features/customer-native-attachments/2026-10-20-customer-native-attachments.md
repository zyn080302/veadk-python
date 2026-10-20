# Native customer attachments

[中文](2026-10-20-customer-native-attachments.zh.md)

ID: customer-native-attachments. Created/revised: 2026-10-20. Status: approved (implementation and acceptance pending).

## Background and scope

SkyEyes already accepts PNG/JPEG/WebP/PDF inline attachments and text attachments with display metadata. CustomerRuntime._new_message and the event projector currently require text-only Content; the native HTTP envelope has a 2 MiB limit. The pinned native Host validates Google Content and retains media in its database; ordinary user input is not echoed as SSE. Its existing policy appends model callbacks. Merely changing input validation cannot complete this integration.

Goal: preserve bounded original native user Content through the standard Harness App, Runtime, Host and session history, with PDF conversion only at the business Host model boundary. No new URI fetching, media output, tool execution, Shared attachment contract, production deployment, distributed session recovery or quota implementation is introduced by this change. These remain obligations of the overall SkyEyes blueprint.

## Scenarios and requirements

- FR-1: Given native protocol, an image/PDF or text attachment with metadata reaches the Host unchanged; metadata is opaque bounded JSON, never interpreted as configuration. Accept snake/camel aliases without ambiguity. Permit attachment-only input. Shared remains text-only.
- FR-2: Before remote effects validate one user Content, at most 8 parts and 3 inline blobs, PNG/JPEG/WebP/PDF only, 4 MiB per blob, 5 MiB decoded total, 1 MiB total text, 7 MiB JSON message. Canonical standard or URL-safe Base64 (GenAI emits URL-safe JSON); normalize to standard Base64, matching magic bytes, optional display_name (1–180 characters). Metadata: JSON object, 16 KiB total, depth at most 8 and 256 values per message. Unknown fields, URI/fileData, thought/function parts, ambiguous aliases, malformed/empty payloads and excess resources fail with fixed codes containing no payload.
- FR-3: The native initial request can use an independent 8 MiB envelope in CustomerRuntime; CustomerChannelClient adds max_initial_request_bytes=None (defaults to max_request_bytes). Only the native first HTTP uses it. Default tools/batches remain 2 MiB and output events 1 MiB. Validate the full initial envelope before session HTTP. No change to Shared sizes.
- FR-4: The original attachment stays in local ADK and remote Host history; continuation sends only the new message. Recovery of completed display does not replay attachments/tools; local journal stores projected assistant/tool events only. No store schema/limit increase. Existing cancellation, identity isolation, ACK and final ordering remain.
- FR-5: SkyEyes composes its existing cancellable/limited PDF renderer after customer policy in the Host before-model callback chain. It preserves prior callbacks and original user events and changes only model request copies. Rendering failure/cancellation prevents the model call; images/text retain contents and metadata.

## Design and affected contracts

Add an internal messages.py validator used by Runtime and native-channel input projection. Keep text-only projection as default; CustomerAdkEventStream derives native capability from its dispatcher client. Normalize input aliases without silently dropping data. Shared does not gain attachments by accident. Native transport separates initial envelope budget from subsequent tool-result budgets. Do not raise SSE budgets to fit inputs: the pinned Host does not emit ordinary user attachment echoes, and the existing output guard remains required.

Affected specs: runtime-customer CON-4, runtime-customer-channel CON-4, runtime-customer-adk-events CON-1. SDK does not know tycAttachment or tycTransport; business boundary validates them. No frontend, dependencies, state migration, auth change, remote operations or configuration override. Raw attachments are private caller data; do not log or place real customer media in fixtures.

## Tasks and acceptance

| Requirement | Task | Acceptance | Verification | Status |
| --- | --- | --- | --- | --- |
| FR-1/FR-2 | T-1 validator, Runtime/projection wiring | AC-1 original bytes and metadata; invalid inputs rejected before HTTP | tests/runtime/customer/test_native_attachments.py | pass (source integration; installed artifact pending) |
| FR-3 | T-2 independent native initial budget and preflight | AC-2 large valid input succeeds; oversized input/config and tool batches fail without corresponding HTTP | customer attachment/channel tests | pass (source integration; installed artifact pending) |
| FR-4 | T-3 real Runner/Harness/session regression | AC-3 first/follow-up/history/display recovery/cancellation retain invariants | SDK runtime tests and business native-runtime gate | pass (source integration; installed artifact pending) |
| FR-5 | T-4 business Host callback composition | AC-4 actual pinned Host sees rendered PDF; original history intact; failure/cancel never calls model | business native and native-runtime gates | pass (source integration; installed artifact pending) |
| All | T-5 reconcile bilingual docs and deliver fixed SDK then business integration | AC-5 required gates and version-bound evidence, independent branch pushes | AGENTS.md gates; fixed installed SDK business gates | not_run |

Targeted command: python3 .codex/run_offline_tests.py tests/runtime/customer/test_native_attachments.py. Full SDK: isolated equivalent of uv run --extra dev pytest -n 2 -m "not codex_smoke and not piagent_smoke"; pre-commit before commit after remote sync. Existing .github/workflows/harness-sidecar-release-gate.yaml already includes tests/runtime/customer, including new regressions. Business scripts/check.py --scope native and --scope native-runtime require fixed customer/Host sources and isolated environments; installed artifact mode must follow SDK delivery. Actual model/Gateway and original customer 20-question A/B remain separate outstanding acceptance.

## Risks and review

Base64 and JSON copies increase memory bounded by the message limits; concurrent admission remains a separate blueprint task. Generic metadata bounds may reject unsupported clients; SkyEyes metadata fits the envelope. Full media histories can grow over many turns; retention/production recovery still requires later work. No new logs, tokens or media dumps. Model callback order must preserve customer tool policy; validate against pinned source, not a mock-only callback.

Review performed directly because review-spec skill is unavailable: checked bilingual equivalence, ownership, alias handling, input/output budget separation, cancellation, persistence boundaries, Shared compatibility and reachable gates; no design blockers. User authorization: “你来按蓝图完成适配、性能优化”, plus independent branch commit/push authorization; no merge/deployment authorization. Status approved records that existing authorization, not a new user confirmation. Production completion and real A/B are not claimed.

Review update: real GenAI Blob serialization uses URL-safe Base64 for JPEG bytes. The first implementation rejected that valid SDK output (1 fail / 149 pass); accept either canonical alphabet and reject mixed/noncanonical encodings. This is required for byte-preserving native Content compatibility.

## SDK and fixed Host source progress

2026-10-20, parent SDK e5f036052: five new real Runner regressions failed on unchanged code with unsupported_user_message. Targeted customer suite after implementation: 336 pass. Two standard Harness media/history tests were subsequently added and are included in the ongoing full gate. Business fixed Host source integration: 7 pass through actual cross-process SDK/standard Harness, original MCP tools and pinned Host, including media first turn/follow-up/local and Host original history. The first PDF Host regression failed on unmodified business composition because PDF reached the model unchanged. Host source-mode evidence is not installed-wheel, Linux or production acceptance. Remote synchronization fetched skyeyes-user branch and origin/main; both are already HEAD ancestors (e5f036052 and 402a3da9), so no rebase changes are needed. At that checkpoint the final gates were pending; the SDK result is recorded below. Fixed artifact acceptance is still outstanding.

## SDK final gate (2026-10-20)

PASS: python3 .codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke' — 7899 passed, 50 skipped, 4 xfailed, 6 subtests passed in 408.13 seconds. Skipped/expected failures are not passed acceptance. Both standard Harness attachment routes are included. Pre-commit all five hooks passed; paired links and whitespace passed. Source scope is parent e5f036052 plus this attachment change; no runtime/test edits occurred during the final run. Branch synchronization remains the previously fetched ancestor check described above.

The first full run returned 7896 passed and three preparation errors: isolated sidecar-wheel tests could not download setuptools/setuptools-scm. Prepared only public build dependencies in a dedicated offline cache using the test environment's uv 0.13.1, then reran those three unchanged tests successfully and the full suite above. No gate was removed or weakened. The offline wrapper uses synthetic configuration and blocks non-loopback Python network calls.

Business c8f4308 already records 36 fixed Host checks and 7 source-mode cross-process checks passing. T-1 through T-4 have source-mode evidence. T-5 remains open for the clean wheel, fixed business installation and corresponding artifact acceptance; delivery state is maintained in the [business attachment record](/Users/bytedance/Workspaces/VolcengineProjects/SkyEyes.worktrees/mr-20261019/docs/project/customer-native-attachments-design.md). No production/cloud or original 20-question result is claimed.
