# AI OPS extension contract

[中文](README.zh.md)

Component: aiops-extension. Status: active. Revised: 2026-10-15. Owned code: veadk/extensions/aiops; compatibility exports: veadk/aiops. [Change](../../prd-spec/features/aiops-extension/2026-10-15-optional-plugin.md).

- CON-1: Public AIOpsExtension, AgentConfig, AgentPlugin, BuildContext, AgentManifest imports are dependency-light. No Core import, entry-point discovery, process, network or environment mutation on import/construction.
- CON-2: apply(agent) is identity-preserving when disabled. create_agent/create_app require enabled=True. Activation chooses exactly one veadk.aiops.backends registration by trusted name and requires api_version=1 with callable create_agent/create_app. The default agentkit fallback imports only the fixed existing package when no registration exists. Unknown names, duplicates, incompatible APIs and nested dependency failures are errors; no fallback after backend failure. Resolution is cached per extension; failed resolution is not cached.
- CON-3: Configuration and domain plugins are captured at construction; per-agent tool factories remain Core-owned. A supplied Agent must be fresh; repeated composition fails under Core's existing contract. Concurrent invocations do not share provider resources. Backend registration contains code and is trusted installation input, never customer prompt or JSON import strings.
- CON-4: Only the public optional native provider hook is supported by the new extension. report_only is rejected before Core loading because the current backend patches SDK globals. Provider lifecycle follows the consumed asynchronous stream, including early close/cancellation/error. Model/tool history remains Codex-owned. Credentials are excluded from repr/config serialization and never placed in docs or tests.
- CON-5: Old config/plugin/manifest paths alias the canonical types. Legacy hosting wrappers preserve call signatures and server behavior. They do not promise removal of legacy server compatibility patches. Ordinary Agent/Runner, HarnessExtension, default package dependencies and Studio routes remain unchanged. No plugin state is persisted; existing native session storage remains authoritative.

Example: AIOpsExtension(config=AgentConfig(name="ops", instruction_source="harness_config")).apply(fresh_agent). create_app() returns the native ADK App; its lifecycle is owned by the native host. The extension starts no sidecar and has no artificial close method. Core/provider errors propagate; errors must not be converted to empty successful reports.

Verification: tests/extensions/aiops covers CON-1–3,5; provider contract/native tests cover CON-4. Installed Core composition verifies the actual boundary. CI and executed results belong to the linked change record; no cloud deployment is implied.
