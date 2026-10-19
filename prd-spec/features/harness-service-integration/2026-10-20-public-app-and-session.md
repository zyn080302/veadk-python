# Public Harness App and session integration

[中文](2026-10-20-public-app-and-session.zh.md)

Change ID: harness-service-integration. Created/revised: 2026-10-20. Status: stage implementation; targeted verification and pre-commit passed, repository-wide regression not green.
Component: [harness-service](../../../specs/harness-service/README.md).

## Background and goals

The approved SkyEyes integration blueprint requires the standard HarnessApp to host an existing Agent and timed DatabaseSessionService. At official base 402a3da, importing the class constructs an environment Agent/App, and ShortTermMemory cannot accept an existing service. Its create_session scans all sessions before a point lookup and logs a connection URL. These behaviors add startup/work and can expose credentials.

This first change implements the P0 prerequisite. The full user goal still includes business integration, overload defenses and customer runtime support; they are subsequent changes, not removed scope. No frontend behavior, model selection, database schema, cloud resources or deployment is changed here.

## Requirements and scenarios

- FR-1: Importing HarnessApp does not construct an environment Agent, default App or database service. Explicit default ASGI access and the module CLI retain their behavior.
- FR-2: ShortTermMemory(session_service=service) reuses the exact BaseSessionService, excluding it from serialization/repr. Conflicting storage configuration fails clearly. Existing backend constructors and callbacks remain supported.
- FR-3: create_session gets the exact session, creates only if absent, and does not list user history or log a database URL. Storage and cancellation errors propagate; new-session callbacks execute only on actual creation.
- FR-4: Existing default HTTP contracts, SDK consumers and business tests remain green. All regression tests use synthetic identities/configuration and local storage.

Given two callers importing the class, neither starts a default runtime. When ASGI tooling retrieves app, one default App is cached. Given a caller-owned session service, Runner and App use that same service. Given many sessions and an existing target, only one point read is needed. Given a storage failure or cancellation, no replacement/empty success is produced.

## Design and contract impact

Remove eager default Agent import and default App construction; expose create_default_harness_app and cached get_default_harness_app. Module __getattr__ preserves legacy app/harness_app imports and Uvicorn module:app; module execution calls the getter. Keep the public class import path. Factory caching is guarded by a process-local lock so concurrent first access constructs only one App; the cache reset helper is private and is not a user request API.

Add a Pydantic input aliased as session_service, excluded from repr/dump, retaining the existing read-only session_service property. Injected storage takes precedence only when no db_url/backend/db_kwargs/backend_configs conflict exists; reject ambiguous configuration. The caller owns storage disposal; this change does not close externally supplied services. Existing after-load callback wrapping is retained and documented; callers must not share a service with differing callback wrappers.

Remove the unconditional DatabaseSessionService list_sessions branch. Retain get/create and after-create callback semantics. Concurrent creation of the same absent ID still follows the storage backend's conflict semantics; this change does not claim a distributed session lease.

## Tasks and affected files

- T-1 (FR-1): regression tests in tests/cloud/test_harness_app_embedding.py, then veadk/cloud/harness_app/app.py.
- T-2 (FR-2/FR-3): regression tests in tests/test_short_term_memory.py, then veadk/memory/short_term_memory.py.
- T-3 (FR-4): targeted HTTP/memory tests, relevant Harness release gate and broader Python regression; bilingual spec and verification reconciliation.

## Verification and acceptance

AC-1: import with a sentinel environment-agent module does not access it; explicit default factory and existing HTTP tests pass.
AC-2: an injected local service retains object identity/state and rejects conflicting configuration; normal local/SQLite constructors still pass.
AC-3: a local SQLite service with list_sessions replaced by a failing sentinel can create/resume a session; cancellation/error and callback tests pass; logs never contain the synthetic URL sentinel.
AC-4: run `uv run --extra dev pytest tests/test_short_term_memory.py tests/cloud/test_harness_app_embedding.py tests/cloud/test_harness_app_http.py tests/cloud/test_harness_app_contract.py`; before delivery run required pre-commit and broader gates from AGENTS.md. No live model/MCP result is implied.

## Risks and review record

Lazy module attributes can affect introspection; verify explicit imports and module:app loading. Input aliases must not leak the service through Pydantic serialization. Storage callback wrapping is legacy mutable behavior and must remain explicit. No new network/storage permissions are introduced.

User scope approval: 2026-10-20 instruction to implement the already delivered SkyEyes blueprint. Direct design review (review-spec skill unavailable) completed before code/tests: requirements/spec, backwards-compatible imports, state ownership, cancellation, credential handling and bilingual equivalence checked. No unresolved design blocker. Runtime verification is recorded below; no live service acceptance has been performed.

## Implementation and verification record (2026-10-20)

Base: `402a3da9cc1a9b4201411d660b51dd6bf023f06a` plus the stage change containing this design. Python 3.12.13, google-adk 2.7.1, LiteLLM 1.83.14, agentkit-sdk-python 0.8.9, Pydantic 2.12.5. The isolated editable SDK is a development environment, not the final business dependency lock or published artifact.

- pass: failing baseline established (11 failed / 5 passed); the concurrent default-cache regression then failed with four constructed Apps before the lock was added.
- pass: 114 targeted App/HTTP/schema/memory/Runner/release-gate checks after implementation; Ruff 0.11.12 for changed Python files.
- pass: 193 related regressions across `tests/cloud`, `tests/runner`, `tests/integrations/agentkit/test_app.py`, `tests/test_runner.py`, `tests/test_short_term_memory.py`, `tests/extensions/harness/test_runner_plugins.py`, and `tests/test_harness_sidecar_release_gate.py`.
- The first expanded run had six missing optional knowledge/memory test dependencies. Added the required llama-index core and OpenAI-like embedding packages locally and to the release gate. Another broader run blocked ten loopback proxy fixtures because the local wrapper disallowed all sockets; corrected that wrapper to allow loopback while rejecting external connections/DNS, then all 193 passed. Production networking was unchanged.
- Release enforcement: App and memory regressions plus affected source paths were added to `.github/workflows/harness-sidecar-release-gate.yaml`; CI execution is not_run.
- fail: first repository-wide two-worker regression: 7357 passed, 85 failed, 2 collection errors, 55 skipped and 4 xfailed. Targeted investigation confirmed disabled OpenTelemetry in the local wrapper, an unloaded AnyIO plugin and missing optional anthropic dependency. The environment corrections and baseline sidecar assertion correction are described below; the initial result is retained as failure history.
- pass: synchronized with official origin/main at 402a3da before the final test run; pre-commit run --all-files passed Ruff check/format, Gitleaks, dependency policy and YAML secret scanning. The test workflow uses the existing accepted example placeholder; no scanner rule was bypassed. Go was installed only in task-local storage and its archive verified against the official SHA-256.
- not_run: business artifact installation, real model/MCP/customer acceptance and deployment. These remain required before the corresponding delivery claims.

Tests ran through the local `.codex/run_offline_tests.py` wrapper using the repository `.venv`, a temporary HOME, synthetic configuration and blocked external sockets. The initial parallel run only applied socket guards in the main process; the wrapper now installs the guard through temporary sitecustomize for inherited Python child environments, keeps in-memory tracing enabled and loads the AnyIO plugin. The wrapper invokes `python -m pytest` with explicit asyncio/coverage/AnyIO plugins. It is a local execution aid; committed CI uses the documented pytest paths directly. Required local knowledge/memory test packages are `llama-index-core>=0.14.0,<0.15` and `llama-index-embeddings-openai-like>=0.2.2,<0.3`.


### Release regression reconciliation (2026-10-20)

After correcting the isolated test environment (in-memory OpenTelemetry, AnyIO plugin, Node PATH, anthropic 1.3.0 and openai-codex 0.159.2), the original failures reduced to one existing sidecar test. A clean source archive of 402a3da reproduces it: test_run_wraps_child_with_sidecar_environment expects port 18787 even though the binding exposes a dynamically allocated loopback proxy. The test and sidecar implementation are byte-identical to the baseline.

T-4 / AC-5: reconcile that regression by capturing the public SidecarBindingSpec returned by the real start_harness_sidecar, then checking that the child receives exactly its model URL and MCP URLs. Also validate the loopback host, /api/v3 path and nonzero port. Keep the real child process and sidecar lifecycle. This is a verification correction needed for the embedding delivery gate; it does not change sidecar production behavior or its component contract. Direct review completed: original failure is reproduced, the new assertion verifies exported effective configuration, and fixed port weakening or runtime bypass is not used. Scope remains the user's approved integration and its delivery verification.

- pass: the corrected sidecar runtime test file passed all 15 tests. The workflow coverage selection passed 144 tests; sidecar.py branch coverage was 96%, above its required 91%. Production sidecar code was unchanged.

### Stage checkpoint (2026-10-20)

- fail: final isolated two-worker repository run (`pytest -n 2 -m "not codex_smoke and not piagent_smoke"`, through the wrapper above): 7507 passed, 6 failed, 50 skipped, 4 xfailed, 6 subtests passed in 423.98 seconds. No test was excluded beyond the repository's default smoke exclusions.
- Five failures depend on external DNS: `tests/cli/test_github_cicd.py::test_list_github_delivery_versions_returns_recorded_versions` and all four tests in `tests/frontend/server/artifacts/test_artifact_library.py`. The GitHub test omits a client substitute when listing commits; artifact URL validation resolves a synthetic hostname before the substituted download. The offline guard rejects both. A clean archive of official 402a3da under the same isolated environment reproduces the identical five failures.
- `tests/plugins/test_codex_sandbox_upload.py::test_upload_retries_while_new_session_data_plane_starts` fails only in the broad run, where its patched sleep observes additional calls. It passes in both the isolated current-source and clean-baseline reruns; the ordering/background-work cause remains to investigate. These findings do not turn the broad gate green.
- pass: the workflow contract test was rerun after changing its synthetic key placeholder; bilingual links/contract IDs and diff whitespace also pass.
- User instruction: submit and push stage progress on independent branches. This is a reviewable development checkpoint, with the remaining regression investigation retained. It is not a release, fixed artifact acceptance, or completion of the full integration blueprint. Remote CI and live business acceptance remain not_run.
