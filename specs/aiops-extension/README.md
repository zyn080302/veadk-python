# AI OPS extension contracts

[中文版](README.zh.md)

Component: aiops-extension | Revision: 2026-10-10 | Status: draft

Public modules: veadk/aiops. Consumer: the separately installed private agentkit_aiops engine. The public SDK owns configuration, plugin/manifest types, lazy hosting and service facades. It contains no investigation engine or private prompt.

- CON-1: AgentConfig is immutable, rejects extra fields and core-prompt overrides, and reserves report time after exploration. Defaults remain exploration_seconds=900, invocation_seconds=2400, max_parallel_tools=4, sidecar_enabled=false, studio_enabled=false.
- CON-2: AgentPlugin validates its name and creates fresh tools through factories. BuildContext hides its environment in repr. Plugins may append customer instructions but cannot replace the private core prompt.
- CON-3: AgentManifest loads a trusted local TOML path and explicit module:factory references. Skill paths resolve relative to that manifest. Do not accept model-authored manifests/imports.
- CON-4: hosting.create_agent/create_app/create_server delegate lazily to the installed private engine. Missing engine has an actionable error; other missing dependencies propagate. Service facades delegate to the same engine and do not implement budgets or reasoning themselves.
- CON-5: Import compatibility does not imply runtime compatibility. Core versions requiring removed Codex native modules cannot execute on upstream main until an explicit adaptation passes the Core and application gates. Do not silently select a different reasoning runtime.

State and concurrency remain owned by the engine; facades add no tasks, cache, retries or persistence. Existing defaults and signatures are restored from the shipped native7 SDK. This restoration does not change the mainline Codex runtime.

Verification: uv run --extra dev pytest tests/aiops/test_contracts.py. Runtime acceptance additionally requires Core tools/check.py, APP tests/run_regression.sh and the authorized live update/first conversation. Source import RED is recorded in .codex/aiops-contract-red.xml (6 failures on the missing module). No live compatibility is claimed.

Related change: [mainline integration](../../prd-spec/refactors/aiops-mainline-studio/2026-10-10-mainline-integration.md).

CON-6: Studio source-preserving MCP overlays must call the application-owned _veadk_studio_mcp_overlay_handler when present. They preserve domain tool wrappers, propagate handler errors, reject non-callable handlers, and traverse child agents. Applications without a handler keep generic MCP replacement unless the validated legacy startup contract in CON-11 applies. Verified by tests/aiops/test_mcp_overlay.py.

CON-7: A source-preserving deployment activates the packaged overlay through `VEADK_STUDIO_SKILL_OVERLAY`, `VEADK_STUDIO_OVERLAY_READY_FILE`, and a single bootstrap prefix in `PYTHONPATH`. Existing application import paths come from trusted Runtime configuration; browser-supplied reserved environment overrides remain forbidden. SDK launch payload tests cover the effective values.

CON-8: `sourceOverlay` is public metadata with `schemaVersion=1` and a complete Agent-name-to-MCP mapping. It contains only MCP names, HTTP URLs, transport and credential environment references. Credentials never appear in the manifest or response. Invalid, missing, duplicate-key or symlink manifests return `status=unavailable` and block editing without stopping the running Agent. Reopening prefers source preservation even when an older ordinary draft exists; the mapping must match the complete Agent graph and all credential references must resolve server-side. Covered by `tests/integrations/agentkit/test_app.py` and `tests/cli/test_studio_rbac.py`.

CON-9: `final.json` defines the exact final Skill selection. Repeated updates cannot revive deselected base-image Skills or silently drop a retained Skill. Legacy overlays without this manifest retain their previous merge semantics. Replacement builds reject unreadable retained overlay Skills and clear the prior overlay directory. OCI recovery follows the authoritative selection and applies directory/opaque whiteouts to lower layers only. Covered by `tests/aiops/test_skill_overlay.py` and `tests/cli/test_legacy_runtime_recovery.py`.

The forced `harness-sidecar-release-gate.yaml` includes these regressions. The current integration is locally implemented but remains draft until live Studio update and first-conversation acceptance; an import test or skipped platform case is insufficient.

CON-10: Overlay bootstrap observes the normal App import without eagerly importing application packages. It preserves dependency selection, wraps App once after module execution, removes its observer, and propagates application import errors. Covered by isolated-process startup regression in `tests/aiops/test_overlay_startup.py`.

CON-11: Application-owned MCP may use the legacy startup environment contract only when trusted published configuration explicitly enables Studio and contains `MCP_SERVERS_JSON`. Studio rebuilds this private environment manifest from the final validated single-root draft, emits an explicit empty list for removal, and publishes only a non-secret bootstrap mode and MCP references in the image. The generated hook validates effective environment against those references and preserves application tool wrappers; an explicit application handler retains precedence. Invalid configuration or ambiguous topology fails closed with fixed diagnostics. Other MCP ownership paths are unchanged. Covered by deployment payload and generated-bootstrap regressions in the mandatory credentials gate.
CON-12: Source-preserving updates retain the trusted `HARNESS_NAME` application identity regardless of Sidecar enablement. This field is not a Sidecar plan or credential. All existing Sidecar cleanup and browser override restrictions remain; normal generated deployments retain their previous filtering. Deployment payload and generated App startup regressions must verify the identity together with the MCP manifest.

## Harness App proposal (2026-10-10)

CON-13: The opt-in fixed-configuration AI OPS host consumes the prepared `agentkit/v1` `AGENT_CONFIG` contract from `agentkit-studio/servers/harness_app_server`. It returns only validated original configuration (environment references, never resolved values) through `GET /agent_config` with `Cache-Control: no-store`, and serves `/healthz` only after assembly. Credentials are resolved in process; invalid, duplicate, unsafe, oversized or unresolved configuration fails before ready. Customer `agent.instruction` is supplementary and cannot replace private system rules. Ordinary serving and Studio channels share the same engine and session store. No default SDK behavior changes. Implementation and real cloud validation remain pending; see [feature design](../../prd-spec/features/aiops-harness-template/2026-10-10-harness-template.md).

CON-14: An empty generic Harness configuration exposes no Skills or tools. Concrete Agent plugins own local tools and domain assets; explicit Studio Skill and MCP selections are authoritative and never fall back to prior image selections. Non-Harness legacy Agent defaults are unchanged. Skill downloads are isolated, bounded and cleaned on failure or cancellation. Unsupported built-in capabilities and knowledgebase bindings fail explicitly.

CON-15: AgentConfig.instruction_source=harness_config makes the immutable YAML supplementary instruction authoritative; the host does not mount a second SQLite editor or apply stale source overlays. Ordinary hosts expose instructionExtension=true only when a trusted instruction editor has been mounted. Studio run snapshots may carry text Skills and long_running tool declarations; no run snapshot means no Studio tools. Capability flags advertise only implemented protocol features.

### Source-preserving overlay filesystem
Studio updates inherit the image runtime user. Build artifacts use explicit read/traverse modes and content-addressed directories; updating does not require deleting files owned by the parent image. The generated layout marker, image environment and control-plane Runtime environment select one identical revision. OCI Skill recovery validates the marker and the selected revision manifests, excludes inactive historical overlays and preserves fixed-path compatibility. No credentials are persisted in these manifests.

CON-16: Explicit source-preserving updates use the existing application deployment lifecycle. CustomCreate passes editMode to ProjectPreview; recovered structured drafts do not imply MPA Profile support. Omit MPA Profile/smoke stages and calls for this mode, while preserving regenerate/new MPA flows and their errors. Runtime publication failures remain failures. Covered by the real ProjectPreview lifecycle regression in mandatory npm test; live GUI completion remains required.

CON-17: Source-preserving validation accepts absent static instructions because runtime-owned instructions remain immutable. All other validation and ordinary creation/regeneration prompt requirements remain enforced.
