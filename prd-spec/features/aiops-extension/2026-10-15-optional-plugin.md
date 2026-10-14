# Optional AI OPS extension

[中文](2026-10-15-optional-plugin.zh.md)

Change ID: aiops-extension. Date: 2026-10-15. Status: implemented. Contract: [aiops-extension](../../../specs/aiops-extension/README.md).

## Evidence and scope

Mainline d55fe8fa has HarnessExtension, but no veadk.aiops namespace or invocation provider factory. The existing AI OPS SDK branch exposes config/plugin/manifest and hosting imports; installed Core 0.1.46 imports those contracts. Core uses a programmatic provider when available and otherwise patches legacy SDK internals. The user explicitly requested integration like HarnessExtension after updating the customer test Studio. That separate task is complete: Studio Revision 53 updated the old database through its official publish API, with three successful real conversations. No GUI publish-button claim is made.

## Goals and requirements

- FR-1: Expose AIOpsExtension through veadk.extensions.aiops. Merely importing veadk or this extension must not load/install/start Core or discover third-party plugins. Explicit apply/create operations enable execution.
- FR-2: Select an installed backend using entry point group veadk.aiops.backends, API version 1. Selection is trusted Python configuration. Reject duplicate names, incompatible APIs and backend errors. For existing images, only the default agentkit name may resolve the fixed legacy agentkit_aiops module when no registration exists. Never fall back after a registered backend fails.
- FR-3: Keep AgentConfig, AgentPlugin, BuildContext and AgentManifest identities across the old veadk.aiops and canonical extension imports. Legacy hosting signatures continue to work; no default dependency on private Core.
- FR-4: Disabled apply returns the exact supplied Agent without loading a backend or running domain factories. Enabled apply composes a fresh Agent once and preserves Core's domain plugin semantics. The extension owns no process or invocation resources.
- FR-5: Add only generic optional Codex provider hooks to the existing runtime. Defaults preserve direct/shim behavior and native tool/history ownership. Provider resources close on completion, exception, cancellation and stream close. Existing admitted tool names/schema remain authoritative. Shell/compaction/result-budget settings retain their current defaults unless explicitly configured.
- FR-6: The new extension requires the public provider hook before loading Core and rejects report_only, whose current implementation patches SDK globals. Existing hosting.create_server remains a legacy compatibility entry point and is not promoted as a patch-free extension lifecycle.

Non-goals: change Studio UI, update customer Agents/images, replace Codex's loop, rewrite Core's operational logic, or migrate all legacy server patches. No new cloud writes are required for this SDK change.

## Design and scenarios

AIOpsExtension(config=AgentConfig(...), plugins=(...), enabled=True, backend="agentkit") exposes apply(agent), create_agent() and create_app(). The explicit object stores configuration and the lazily resolved backend; it does not scan plugins at import time or write environment variables. Backend API 1 provides create_agent/config/plugins/agent and create_app/config/plugins/agent compatible factories. Domain plugins remain ordinary functions, tools and ADK callbacks. An installed registration is selected exactly once; failures propagate, including missing transitive dependencies.

Given Core absent, ordinary Agent and disabled apply remain usable; explicit AI OPS creation raises an actionable dependency error. Given two registrations with the requested name, resolution fails before loading either. Given a provider stream cancelled or closed early, its async context closes exactly once. Given two concurrent invocations, each receives its own endpoint and admitted executors.

Canonical contracts move under extensions/aiops; old modules re-export the same classes. Generic provider_factory is callable-only, excluded from serialization/schema, retained by configuration copying, and never supplied by a Studio string. The provider owns authentication/transport; its endpoint does not receive unrelated model headers. The core package remains independently released.

## Tasks and affected files

- T-1 / FR-1–4,6: extension modules, legacy shims, backend registration contract, paired READMEs and example.
- T-2 / FR-5: runtime/codex/config.py, provider_extension.py, runtime.py; reuse the reviewed provider behavior without unrelated branch changes.
- T-3: contract/negative/import tests, provider lifecycle/native runtime tests, packaging entry-point integration and CI gate.
- T-4: actual installed Core composition test with the candidate SDK; baseline regressions, pre-commit and review; commit/push only this SDK's public code to the user fork.

## Acceptance and commands

| Requirement | Task | Acceptance | Evidence |
|---|---|---|---|
| FR-1–4,6 | T-1,3 | AC-1: no implicit dependency or discovery, identity compatibility, exact disabled behavior, selected backend checks | tests/extensions/aiops; pass |
| FR-5 | T-2,3 | AC-2: default transport equivalence, isolated provider lifecycle and tool admission | tests/runtime/codex; pass |
| FR-1–6 | T-4 | AC-3: actual Core produces usable Agent/App through the extension without SDK global patches | local isolated integration; pass, 2 source and 2 installed-SDK tests |
| FR-1–6 | T-3,4 | AC-4: required gates and clean public diff | pytest -n 2 -m "not codex_smoke and not piagent_smoke"; pre-commit run --all-files; pass (equivalent pinned scanner execution below) |

Use the repository environment with uv run --extra dev. Native smoke runs serially with CODEX_RUN_SMOKE=1 and must actually execute. Credential-free local protocol fixtures prove integration without sending customer data to a model. Live cloud/browser checks are not required for this SDK-only change; the separate Studio API acceptance is complete.

## Review, authorization and risks

The user explicitly approved plugin-style implementation and minimizing existing-version impact in the current request. This design implements that direction without a breaking change or production rollout. review-spec skill is unavailable; direct review covers API ownership, optional dependency loading, duplicate registrations, error propagation, cancellation, ordinary-agent isolation, compatibility and bilingual equivalence. No design blocker remains.

Risks: old Core creates legacy server patches if callers explicitly use create_server; this is documented, not silently represented as removed. A new SDK cannot retroactively change an existing image. A missing backend is an error only on activation. The existing Core 0.1.46 distribution still pins the previous SDK. Source API compatibility and candidate-wheel execution do not prove normal resolver installation; a matched Core/SDK release is required before customer upgrade.

## Executed verification (2026-10-15)

Scope: this branch on origin/main d55fe8fa, fetched and rebased before final checks. Use `UV_PROJECT_ENVIRONMENT=../database-v4-skill-mcp-20261013/.venv PYTHON_DOTENV_DISABLED=1 uv run --no-sync --extra dev` with the existing prepared repository environment.

- `pytest -n 2 -m "not codex_smoke and not piagent_smoke"`: pass, 7089 passed, 53 skipped, 4 xfailed, 6 subtests passed. Two workers limit local resource use.
- Expanded runtime/Harness tests: pass, 555 passed, 25 skipped, 13 deselected. An initial run had 29 tracing failures because `OTEL_SDK_DISABLED=true` disabled the behavior under test; removing that test-only setting resolved all failures. Failed evidence is retained locally.
- `CODEX_RUN_SMOKE=1 ... pytest -m codex_smoke -p no:xdist -rs`: pass, 12 executed, 2 skipped because database test configuration was absent. Includes a real local CLI/provider/MCP loop and final output; no cloud model or customer data.
- Candidate SDK plus Core 0.1.46 source: pass, two tests; installed candidate SDK wheel plus Core source: pass, two tests. Each tests repeated conversations and unchanged SDK function identities. These private Core fixtures are kept outside the public SDK.
- Wheel: pass, 14 source files match; no default Core requirement. Verification wheel version `0.0.0` is not a release.
- Pre-commit: pass, Ruff check/format, Gitleaks 8.24.2, dependency policy and YAML secret checks. The first attempt exited 143 during Go installation. The rerun used the already verified same-version local Gitleaks binary and a temporary config changing only that hook's execution language/path; original `git --pre-commit --redact --staged --verbose` scope and all other checks remained identical. Repository hooks are unchanged, no scanner was skipped.
- Implementation review: pass. Optional activation, old type identities, callable serialization exclusion, provider lifecycle, concurrent invocation isolation, and tool admission checked. Legacy server patches and published dependency pins remain documented boundaries.
- Cloud release and template upgrade: not_applicable to this SDK change. No customer Runtime writes.
- After mainline synchronization: `pytest tests/extensions/aiops tests/runtime/codex tests/test_harness_sidecar_release_gate.py -m "not codex_smoke" -q`: pass, 393 passed, 25 skipped, 14 deselected; exit 0.
