# AI OPS mainline and Studio update integration

[中文版](2026-10-10-mainline-integration.zh.md)

- Change ID: aiops-mainline-studio
- Date: 2026-10-10
- Status: implemented


## Final acceptance (2026-10-10)

Status: implemented. Upstream synchronization advanced to `812faadfe9952d47d1efc7b0a32595beafa58b91`; the private Core and plugin bases remain c51d2640 and 440ddeea. The inherited guided Studio upgrade fixes remain included without changing normal upgrade defaults. Historical checkpoints below retain their original failure/pending evidence.

AC-1 through AC-9: pass for the authorized scope. Mainline compatibility was completed through the [Harness template design](../../features/aiops-harness-template/2026-10-10-harness-template.md), with current/historical SDK gates and real native CLI tests. SDK regression: 7159 passed, 70 skipped, 4 xfailed. Frontend: 1386 Node and 72 React tests; build/assets and pre-commit passed, zero new Pyright diagnostics.

The actual second Studio update from V55 to V56 completed through the normal confirmation page. Two Skills and five authenticated MCP connections survived reopening. Skill activation receipt and final answer carried the h2 marker; MCP documentation calls succeeded after the model corrected an initial parameter error. V60 retained the new mainline image and restored the legacy environment; a fresh session repeated the Skill/MCP acceptance. Nine protected Runtime versions/configuration fingerprints were unchanged. The Chinese guide includes reviewed, redacted screenshots. The cloud Studio Function and update channel were not upgraded; clients need a Studio version containing these fixes.

## Evidence and scope
Upstream VeADK main is 171d8d86. The newer deployed SDK uses native7 and exposes veadk.aiops; main lacks that package and removes native_bridge/native_responses. The specific old application used for this validation instead runs SDK 1.1.7.dev33+g788459adf.baisheng.20260919.4. Core main c51d264 still imports the removed modules. APP main is 440ddeea. Studio upgrade fixes f94b5960, 5ca502ad, and 814da374 are outside upstream main.

The user authorizes mainline alignment and a real Studio Skill/MCP update on the old application Agent only. Customer v4-2 and other old v4 Agents are protected. No cloud resource enumeration or remote instance shell is allowed.

## Requirements and design
- FR-1: Create isolated branches from each verified mainline and preserve unrelated worktrees. Reconcile the three existing Studio upgrade fixes without altering normal upgrade defaults.
- FR-2: Restore public AI OPS configuration/plugin/hosting contracts separately from the private engine. Keep the current upstream Codex implementation. Do not deploy a mainline wheel until actual Core compatibility and mandatory gates pass.
- FR-3: Preserve application source, existing environment/credentials, and Skill/MCP semantics through Studio updates. Credentials stay in process or authorized secret storage, never source or reports.
- FR-4: Perform one actual Studio update on the authorized application Runtime, follow the same task/candidate to completion, verify the first conversation and edited Skill/MCP through official APIs, then compare protected resource fingerprints.
- FR-5: Produce a Chinese customer guide with actual redacted screenshots and verified results; explicitly distinguish pending steps.

## Tasks and acceptance
| Task | Requirement | Acceptance | Check |
|---|---|---|---|
| T-1 | FR-1 | AC-1: isolated trees contain fetched mainline | git ancestry and clean-base check |
| T-2 | FR-1 | AC-2: upgrade compatibility preserved | historical consumer, guided release, CLI contract tests; release gate |
| T-3 | FR-2 | AC-3: public contracts and actual Core assembly work | public contract tests, Core tools/check.py, APP tests/run_regression.sh |
| T-4 | FR-3 | AC-4: source and credential boundaries preserved | source-preserving backend/frontend regressions and required build/type gates |
| T-5 | FR-4 | AC-5: real page update and first conversation succeed; other Runtime versions/configurations unchanged | candidate/task/release evidence and exact before/after comparison |
| T-6 | FR-5 | AC-6: customer can follow screenshots | guide and image/link review |

## Contract impact and risks
Existing Studio upgrade contracts remain unchanged during cherry-pick reconciliation. Public veadk.aiops restoration and adaptation of the changed Codex runtime need a separate component contract assessment before implementation. The old native runtime must not replace upstream modules. Runtime import incompatibility currently blocks use of a mainline SDK in production. Browser login and exact Runtime connection have not completed.

## Review and verification record
User authorization is the current request to align mainline and validate the old v4 application only. Local reconciliation of the three already implemented upgrade fixes is within that scope. New runtime behavior changes remain under review. Direct design review replaces unavailable review-spec: source protection, secret boundaries, forbidden enumeration, first-conversation acceptance, and release provenance are explicit. Mainline trees pass AC-1. Other criteria are not_run. No production code changed and no cloud writes at design creation.

## Source-preserving MCP regression
2026-10-10: the shipped native7 regression tests/aiops/test_mcp_overlay.py fails all 3 cases on main. The generated sitecustomize replaces application-owned MCP tools instead of calling _veadk_studio_mcp_overlay_handler. This bypasses application policy ownership, hides handler failures and drops the application wrapper. Restore the existing handler branch before generic replacement: callable handlers own the update; invalid handlers fail; exceptions propagate; recursive child traversal remains. This is restoration of the deployed extension contract, not a new MCP execution mechanism. Regression must be included in the mandatory gate. Mainline Studio upgrade checks: 293 passed, 8 skipped on macOS; skipped Linux execution cases remain unverified.

## Overlay activation regression
Mainline RED: 5 failures (3 missing-helper imports and 2 actual deployment payloads missing the overlay environment). Restore the existing native deployment contract: retain trusted Runtime PYTHONPATH, prepend the bootstrap exactly once, and explicitly send overlay paths through the SDK launch configuration. Browser environment overrides remain rejected. The actual deployment regression and helper cases are mandatory credentials-gate checks. This bounded reconciliation does not migrate the Codex engine.

## Reopening source-preserving updates
FR-3 also requires a second update to use the latest image overlay, preserving application code and MCP ownership. Restore native7 public sourceOverlay metadata validation, route recovery precedence, and MCP graph identity recovery. Invalid/missing manifests block editing without breaking the running Agent. Add the original six manifest regressions before implementation. These checks contain synthetic credentials only and must run in the mandatory gate.

## Repeated Skill selection
Three offline RED cases reproduce deselected base-image Skills reappearing after a second overlay, and missing preserved Skills being silently omitted. Restore the shipped final.json contract: exact final selection, build-time validation of opaque preserved overlay Skills, removal of superseded overlay directories, and OCI manifest/whiteout-aware recovery of the authoritative Skill directory. Preserve upstream changes to MCP credential handling. Verify generated bootstrap against the real Google ADK SkillToolset, plus offline OCI layers and existing recovery tests.

## Offline verification checkpoint (2026-10-10)
- Full Python regression: 6,767 passed, 74 skipped, no failures/errors; two workers with frozen dev/codex/extensions/sandbox extras.
- Mandatory backend gates: coverage 149 passed/1 skipped, lifecycle 9 passed, credentials 121 passed, release 81 passed; sidecar coverage 96% (threshold 91%).
- Frontend tests/build passed; sidecar 22 tests passed, lines 100%, branches 94.44%. Pre-commit passed including secret scans.
- Linux historical consumer checks on the authorized isolated Devbox: 4 passed, no skips.
- Targeted Pyright rerun resolves the added OCI test diagnostic. Upstream diagnostics remain; this is not a globally green type check.
- Real local Studio recovered the exact old application V46 and its 1 Skill/5 MCP entries; ZIP import selected the verification Skill. No Runtime writes yet. FR-4 will use two distinct updates to test MCP removal and restore the original five services, each submitted once.
- AC-3 actual Core assembly against the mainline SDK remains blocked by removed native engine imports. These checks do not justify replacing the deployed SDK wheel. AC-5/6 remain pending.

## Startup import ordering badcase
The first real GUI update built successfully but the candidate failed importing `google.adk.tools.skill_toolset` before serving requests. The image contains separate system and application Python environments. The generated `sitecustomize` eagerly imports `google.adk.apps.app`, before the application selects its dependency path, and can cache the wrong ADK package. Registry config retrieval was denied, so image-level PYTHONPATH loss remains unconfirmed.

FR-6 / T-7 / AC-7: registering the overlay must not import application packages during interpreter initialization. Install a one-shot import observer for `google.adk.apps.app`; patch App only after its normal loader executes, preserve loader behavior, remove the observer, and handle already-loaded App idempotently. Errors during application loading must propagate. Preserve current Runtime environment behavior in this fix. Add isolated-process regression with a stale system ADK and the actual installed application ADK, plus already-loaded and failed-loader cases, to the existing mandatory `tests/aiops` gate. No dependency upgrade or remote shell. Direct review: in-scope repair of FR-3, authorized by the user's Studio validation request; no public API change. Live acceptance remains pending.


## Legacy application MCP startup compatibility
The second GUI candidate passed the import-order failure but failed before App construction: `Studio MCP source manifest is required`. The exact published application consumes `MCP_SERVERS_JSON` during startup and owns its policy wrapper; it has no overlay handler. The deployment path removed that environment field for application-owned MCP. The same old application permits exactly one report Skill, so live validation must replace the complete existing report Skill by name instead of adding another Skill.

FR-7 / T-8 / AC-8: for application-owned MCP only, trusted published configuration with `VEADK_STUDIO_ENABLED=true|1` and an existing `MCP_SERVERS_JSON` selects the legacy environment bootstrap contract. Rebuild the manifest from the final server-validated draft and credential references, including an explicit empty list after removing all MCP services. Keep secrets only in Runtime environment. Generate a public `mcp-bootstrap.json` mode descriptor alongside `mcp.json`. Restrict this flat bootstrap to a single root Agent; reject ambiguous graphs. At App construction verify the effective environment exactly matches the public mapping and referenced credentials, then preserve the application's tools; an explicit application overlay handler still owns updates. Missing/malformed/mismatching configuration fails with a fixed diagnostic without echoing values. Other application, Sidecar and platform paths retain existing behavior.

Verification: add actual deploy-payload RED regression, generated-bootstrap wrapper/empty-list/topology/mismatch/credential-boundary cases, and an offline check using the exact historical consumer outside the public repository. Existing mandatory credentials gate already includes these test paths. Review: the user's scoped Studio validation authorizes this compatibility repair; no additional resource or product scope. Direct review found no remaining design blocker; live acceptance remains pending. Keep failed candidates as evidence. No claim that the old Agent runs the mainline SDK.

## Application identity preservation
The third candidate built successfully but failed MCP identity validation. Exact version metadata confirms that the source version has `HARNESS_NAME`, while the failed candidate does not; all four MCP credential references match. The broad `HARNESS_` environment filter incorrectly treats application identity as platform Sidecar state. The historical SDK derives the root Agent name from `HARNESS_NAME` and otherwise defaults to `harness_app`.

FR-8 / T-9 / AC-9: source-preserving updates retain the trusted application's `HARNESS_NAME`, independently of Sidecar enablement. Continue clearing old Sidecar plans, bindings, hashes and credentials. Normal generated deployments keep their existing filtering. Browser environment overrides remain rejected. Add a failing actual deployment-payload regression and an offline App startup test using the filtered environment, plus enabled/disabled/absent identity boundaries, to the mandatory gate. Review: this repairs FR-3 within the user's authorized scope, changes no public API, and must not weaken MCP identity checks. Live acceptance is still pending.
