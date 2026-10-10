# AI OPS Harness App template

[中文版](2026-10-10-harness-template.zh.md)

- Change ID: aiops-harness-template
- Date: 2026-10-10
- Status: implemented
- Authorization: the user explicitly requests implementing the Harness App interfaces, updating the image, and verifying Studio parameter updates. Existing authorization limits Runtime writes to the old application v4; customer v4-2, other Agents and the cloud Studio Function remain protected.


## Final acceptance (2026-10-10)

Status: implemented. This record supersedes the pending statuses in the historical checkpoints below. The synchronized upstream base is `812faadfe9952d47d1efc7b0a32595beafa58b91`. SDK `1.1.14.dev61+g812faadfe.aiopsharness2`, private Core 0.1.44 and domain plugin 0.1.53 were built and verified on Linux.

| Acceptance | Result | Evidence scope |
| --- | --- | --- |
| AC-1 / AC-3 | pass | YAML, reference isolation, empty selections and actual host/channel regressions; formal health/config/invoke and session follow-up |
| AC-2 | pass | Core mandatory gate: 257 current SDK, 7 real CLI, 302 historical SDK tests; 15 historical-only skips in the current lane |
| AC-4 | pass | Both immutable images reached Succeeded, exact digests verified, dependencies and actual CLI self-tests passed; formal Runtime validation used the application image |
| AC-5 | pass | Actual Studio second update V55 to V56 completed, with zero MPA Profile calls; Skill activation receipt and final answer carried the new marker, MCP documentation read succeeded |
| AC-6 | pass | Chinese customer guide with reviewed, sanitized real screenshots and validated local links |

The new image passed formal Harness configuration acceptance at V58/V59. V58's initial follow-up omitted the requested format marker; a same-session reminder restored it without providing the answer/marker or issuing tools. V59 used a new configuration and passed both turns. Do not report unconditional first-attempt format adherence. The native regression verifies that every upstream request retains the customer instruction.

V60 restored the original entry/environment while retaining the new image. Its fresh-session Skill activation, exact new marker in the paired tool receipt and final answer, MCP documentation call, and sourceOverlay metadata passed. All nine protected Runtime versions and configuration fingerprints remained unchanged. Temporary TYPE was removed once. GetRuntime omitted system tags afterwards; exact-resource Tag.GetResources verified the original complete tag digest without additional writes.

Final SDK regression: 7159 passed, 70 skipped, 4 xfailed. Frontend: 1386 Node and 72 React tests, production build and packaged asset checks passed; changed-file Pyright added zero diagnostics. The domain plugin dual-SDK gate passed 360/1 skipped and 352/2 skipped. Skips do not prove behavior.

Boundaries: no separate generic Runtime was created; the generic image was tested in the build. The Studio template selector was not registered or changed, and the cloud Studio update channel was not published. Harness validation used zero cloud Skills and five MCP connections because legacy overlay Skills have no cloud binding IDs; the restored legacy entry verified the two actual Skills. Screenshots document the real V55/V56 UI, not the later configuration-only API releases. Existing resource scaling stayed 0–10; managed shared remains outside scope.

## Evidence and goals
The reference is agentkit-studio/servers/harness_app_server. Its fixed-configuration image consumes AGENT_CONFIG (agentkit/v1), serves GET /agent_config and /healthz, standard invoke/session/SSE/A2A APIs and studio-tool-channel/1 HTTP/SSE endpoints. Studio recognizes TYPE=HARNESS independently of configuration validity. The current AI OPS Core composes a veADK Agent but lacks this portable YAML host contract. Core still imports native_bridge/native_responses removed by current main; merely importing public configuration or reaching Ready does not prove compatibility.

The preceding source-preserving candidate loads the report Skill, but its first MCP document call failed and sourceOverlay is absent. That candidate is not accepted. This feature extends the preceding integration scope and keeps its regression evidence.

## Requirements and scenarios
- FR-1: A reusable image implements the reference fixed-configuration Harness App contract without depending on the Studio backend or copying SDK execution code. Given prepared agentkit/v1 YAML and separately injected credentials, startup constructs one AI OPS Agent and returns the original safe configuration.
- FR-2: Model, customer supplementary instruction, Skill and MCP updates apply after a deployment restart and can be read for the next edit. Empty selections clear prior selections. Invalid or unresolved bindings fail explicitly before serving ready; no generated replacement Agent or arbitrary import paths.
- FR-3: Retain the single AI OPS reasoning engine, domain tool policies, budgets, prompt confidentiality and cancellation guarantees. Public VeADK owns public contracts; the private binary owns private reasoning behavior. Reconcile Core with current mainline without replacing upstream default runtime behavior or silently bypassing prompt enforcement.
- FR-4: Studio HTTP/SSE tools use immutable run snapshots, bounded calls, identity/revision checks, cancellation and cleanup. Advertise only implemented capabilities. Ordinary calls must not inherit another run's tools, Skills or credentials.
- FR-5: Publish an immutable candidate image only after offline gates; update only the authorized old application v4. Restore its original five MCP sources, verify real Skill/document calls, configuration round-trip, actual Studio edits and protected-resource fingerprints.
- FR-6: Deliver a template example and Chinese tutorial with real redacted screenshots. Clearly separate image capability, template registration, local Studio verification and any unperformed cloud Studio publication.

## Design and boundaries
Public adapter modules under veadk.aiops parse and validate the versioned YAML and host configuration routes. They reuse SDK Agent/App/session/tool serving and lazy-load the private engine. Domain plugins are explicitly supplied by trusted image entrypoints, not imported from YAML. Existing applications that do not select this host retain their behavior. Runtime tags identify Harness; the image remains fixed for parameter-only updates. Credentials use environment references and never appear in public YAML, errors, images, build contexts or evidence.

The reference's managed shared mode is a different deployment ownership model; this task implements its fixed-configuration template interfaces, using the same ordinary and Studio channel execution. No new investigation state machine or report rewriting model. Runtime native compatibility must be established independently before release. Mainline additions must be opt-in and preserve SDK defaults. Stateful tool channel requires one worker and instance affinity; do not silently change the user's configured scaling.

## Tasks and acceptance
| Task | Acceptance | Verification |
| --- | --- | --- |
| T-1 | AC-1: safe YAML, references, update round-trip | failing schema/secret/duplicate/empty-selection tests, reference-consumer contract |
| T-2 | AC-2: real Core assembly on mainline SDK | actual engine tests including final transport, budgets and events; private mandatory gate |
| T-3 | AC-3: config, health, invoke, sessions, channel | actual ASGI route tests, negative identity/revision/late-result/cancel tests |
| T-4 | AC-4: immutable image reproduces contracts | Linux isolated build, dependency checks, image tests and digest |
| T-5 | AC-5: actual Studio edits work twice on v4 | real UI and formal APIs, candidate provenance, all protected Runtime fingerprints |
| T-6 | AC-6: customer instructions match observed flow | screenshot and Markdown link review |

## Review and risks
Direct design review replaces unavailable review-spec. Configuration stays public and reference-compatible; private credentials are resolved only in process. Parsing and transport are separated from engine logic. No shared Agent mutation between runs, hidden fallback or public private prompt. Regression tests precede behavioral edits; mandatory gates must cover them. User request supplies authorization to implement this bounded design; no new permission is inferred for other Runtime resources or cloud Studio publication. Mainline engine compatibility and the exact image publishing path remain acceptance work, not verified claims.

## Verification record
At design creation: AC-1 through AC-6 not_run. Prior full VeADK regression: 6789 passed, 74 skipped, no failures/errors (6863 collected). Prior V50 Skill activation passed; MCP document call failed. These do not prove this new Harness implementation.

## Mainline transport integration refinement
The current SDK already owns native Codex threads and MCP execution. Retain that path. Add an optional programmatic provider factory to CodexRuntimeConfig, excluded from serialization and unavailable from YAML, that owns a per-invocation async context and supplies an ephemeral model endpoint. The default path remains unchanged. The private engine supplies a local Responses transport adapter at this boundary: private prompt injection, existing report/closeout policies and backend options occur only in memory immediately before provider transmission. It does not execute tools or keep a second conversation. The SDK owns tools, history, final events and cancellation. The factory must close on early return, error, cancellation and consumer disconnect. This replaces obsolete private integration hooks only for current-mainline SDKs; historical compatibility tests remain a separate supported consumer lane. Add offline provider-context lifetime and isolation regression before runtime edits; new private adapter needs actual CLI/model-transport contract tests before image publication.

### Execution policy preservation
User clarification: the generic Harness starts with no Skills or tools. Concrete Agent plugins own domain Skills, local tools and MCP adapters. An empty Harness selection must not reactivate the legacy incident-report fallback or register Skill readers; existing non-Harness consumers keep their behavior. Real Core tests cover empty selections and concrete local tools.

Full-gate finding: Python 3.13 closing a full tapped A2A queue raises QueueShutDown into the original producer. Suppress only that exception for a closed subscription-owned queue, preserving cancellation, unrelated errors and other subscribers. Malformed Skill worker output must yield sanitized HarnessConfigurationError and clean its temporary resources. Existing RED regressions cover both failures.

The trusted provider endpoint may decorate each already registered SDK tool executor through `wrap_tool_executor(name, executor)`. The SDK still owns schemas, callbacks, invocation identifiers, tool admission/counting, output events and history; a decorator only adds invocation-local capacity/closeout checks and delegates once or rejects explicitly. No arbitrary tool registration or second loop is introduced. Factory teardown encloses tool unregistration. Typed optional `compact_prompt` and `tool_output_token_limit` configure native maintenance and output budgets; absent values preserve upstream defaults. `shell_enabled=false` disables native shell for this template. Core reuses its existing task pool and compaction validation, with regression for cancellation, exclusive tools, invalid summaries and 429 before release.

### Full regression checkpoint
The current full suite completed with 6,836 passed, 74 skipped and one failure: the disabled-channel HTTP test still expected the old three-field capability response. Updated that assertion to include skills=false and long_running_tools=false, matching the explicit capability contract. No production behavior changed in this correction. Final full-suite confirmation remains pending.

### Static validation
On 2026-10-10, pre-commit --all-files passed. Pyright analyzed 30 changed/new production files and reported 47 diagnostics. The same environment and corresponding upstream files report the identical 47 diagnostics; added diagnostics: zero. This comparison does not claim the pre-existing repository diagnostics are fixed. The isolated disabled-channel HTTP suite passed all 12 tests.

### Final SDK regression
2026-10-10: the final complete SDK suite passed: 6,837 passed, 74 skipped, no failures/errors (6,911 total). Evidence: `.codex/harness-full-regression-final.xml`. Skips do not validate the corresponding behavior. Linux packaging, image, and live Studio acceptance remain pending.

### Live stateless cache compatibility finding
V51 was Ready but its first live Skill/MCP invocation failed before tools. The private mainline provider combined SDK default caching/expire_at with store=false. Same-model harmless request controls returned 400 with that pair and 200 when only that pair was removed; namespace tools alone were accepted. Correct only the private send boundary to omit stateful cache options while retaining store=false, native history, prompt_cache_key and tool routing. SDK default behavior and public contracts are unchanged. Add RED/GREEN policy and strict real CLI/image fixtures; rebuild and repeat live acceptance. Previous green gates do not cover this finding.

### Non-root source-preserving updates
The first Studio h1 build failed before Runtime update: the inherited non-root user could not read the root-owned validator copied from a restrictive local archive. Removing previous root-owned overlay directories would also fail on the second update. Preserve the inherited USER, CMD and ENTRYPOINT. Generate a deterministic, content-addressed overlay directory for each update, explicitly readable/traversable COPY modes, and no deletion of parent-image files. The Runtime environment and image environment must point to the same new directory. A public, credential-free layout marker selects the active directory during OCI recovery; older fixed-path overlays remain readable. Previous layers retain inactive historical assets as ordinary immutable image history; only the final selected manifests and current folder may be read. Reject malformed layouts, symlinks, missing current manifests and opaque preserved Skills.

This is necessary to meet the already authorized Studio update acceptance. Direct design review: no new remote execution, no elevated runtime user, no private data in layout markers, no change to ordinary generated Agents or non-overlay updates. Add failing regressions for restrictive archive modes, two consecutive overlays with removed resources, Runtime/image path agreement, migration from fixed paths, and unsafe markers; include them in the mandatory gate before retrying the actual GUI build.

### Non-root overlay verification checkpoint
2026-10-10: regression RED reproduced 5 failures. Targeted GREEN: 73 passed. The current mandatory backend workflow passed: coverage 150 passed/1 skipped at 96% (threshold 91%), lifecycle 9 passed, credentials 211 passed, release 81 passed. Full SDK regression: 7,159 passed, 70 skipped, 4 xfailed, zero unexpected failures/errors in 430.164 seconds. Pre-commit passed; changed-file Pyright has 72 existing diagnostics, equal to the frozen comparison baseline, with zero new diagnostics. Evidence: `.codex/nonroot-overlay-full-r4.xml`, `.codex/nonroot-overlay-gates-r4/`, and `.codex/nonroot-overlay-pyright-comparison-r4.json`. The real GUI retry has been submitted on the authorized legacy application only; its build, release and first-conversation acceptance remain pending.

### Restoring hydrated MCP credentials after a browser refresh
V53 built successfully but failed at startup. Its four MCP entries lost their Authorization headers and all credential reference variables; V52 retained five authenticated entries. A restored browser draft still reported credentialConfigured=true with no authTokenEnv. The cause is storage sanitization treating server-hydrated credentials as newly typed secrets and deleting their existing references. Synthetic local startup succeeds with four distinct credentials.

Within the existing Studio update authorization, preserve each configured tool's existing reference while removing its raw token and deployment value. Newly typed/replaced values remain ephemeral, and explicitly cleared authentication remains cleared. Do not copy credentials across Agent/name/URL identities or relax domain validation. The server continues to resolve references against the published snapshot. Existing already-damaged drafts require reopening the exact deployed Agent; do not guess references from tool order. Regression must exercise hydration -> save -> reload -> prepared deployment for root, child and workflow tools, confirm no secret persistence, and retain replacement/removal negative cases. The existing frontend release gate runs these tests. Update the studio-draft-storage component contract and repeat the real refresh/update flow before claiming acceptance.

Direct design review: bounded state serialization change; no new API, secret store, remote shell or resource scope. Existing user authorization covers this prerequisite fix. No visual/component change is required. Implementation and real acceptance remain pending at this checkpoint.

### Deployment identity migration finding
The first current-mainline Harness release failed before App creation. Offline startup with its exact environment reproduces HarnessConfigurationError: the legacy HARNESS_NAME contains the Runtime display name with hyphens, whereas an explicit override must be a valid SDK Agent identifier. The reference Harness rejects the same override. Correct the migration environment to use the validated YAML Agent identity; restore the original environment for the legacy entry. Do not relax identity validation or normalize distinct explicit identities into one namespace. This is a deployment payload correction, not a product contract change or a reason to rebuild identical wheels. A failing payload check and exact-environment startup reproduction precede the correction; add the real-Core identity boundary to the mandatory gate before another release. Runtime version metadata omits system tags, so tag preservation must use Runtime metadata and compare normalized Key/Value fields.

### Live follow-up verification
The first V58 formal invocation passed tool execution, configuration marker and result checks. Its same-session follow-up retained the computed value and issued no tools, but omitted the requested marker. Preserve this failed acceptance. Before attributing it to model behavior, extend the real native two-turn transport regression to assert that the customer instruction reaches every actual upstream request, including resume and 429 retry. No product contract change or additional Runtime publication is required by this observation alone.

The added native transport assertion passed in the full private Core gate: 257 current-SDK tests, 7 real CLI tests, and 302 historical-SDK tests; 15 tests target only historical implementation and are skipped in the current lane. Each actual first-turn, tool-follow-up, resumed-turn and 429-retry request carries the customer addition. No product code changed for the observed formatting omission. In the original live session, an explicit request to follow the configured answer format (without supplying the answer or marker) restored the correct marker and remembered result, with zero tool calls. Record this as acceptance with a follow-up reminder, not first-attempt success.

Existing Runtime updates accepted a Tags field without changing the resource tag. The reference deployment attaches TYPE on creation. The authorized migration used the formal resource-tagging API for the exact Runtime, verified TYPE=HARNESS, and must remove only that new tag when restoring legacy configuration. No image rebuild is needed for this metadata operation.
