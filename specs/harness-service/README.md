# Harness service embedding

[中文](README.zh.md)

Component ID: harness-service. Date: 2026-10-20. Status: implemented locally; release verification pending.
Related approved change: [harness-service-integration](../../prd-spec/features/harness-service-integration/2026-10-20-public-app-and-session.md).

## Ownership and interfaces

HarnessApp owns HTTP/ADK adaptation; the caller supplies its Agent and ShortTermMemory. Model execution, identity authorization and backend storage remain separate responsibilities.

- CON-1: Import `HarnessApp` from `veadk.cloud.harness_app.app` without creating the default Agent/App. `create_default_harness_app()` explicitly constructs one; `get_default_harness_app()` caches one per process. Legacy module `app` and `harness_app` attributes and module execution use the cached default.
- CON-2: `ShortTermMemory(session_service=service)` accepts an existing BaseSessionService and exposes the same object through its read-only property. Conflicting explicit storage options fail. The input is excluded from repr/serialization. Caller owns disposal; legacy callback wrapping can mutate get_session and must not be combined with differing callbacks on a shared service.
- CON-3: `create_session` only gets the exact app/user/session tuple and creates when missing; it never enumerates history or logs a database URL. Creation callbacks run only after new creation. Storage failure/cancellation propagate; duplicate creation uses backend conflict semantics.
- CON-4: Delegated ADK `/run` and `/run_sse` apply `HarnessApp.max_llm_calls` per invocation. `None` leaves ADK defaults; nonpositive values preserve RunConfig semantics. Missing sessions remain 404; ADK owns event shaping, metadata, errors and disconnect cancellation. Explicit Harness overrides retain their precedence. This is a model-call default, not tenant quota enforcement; A2A/live audio are outside this guarantee. Design and verification: [HTTP call limit](../../prd-spec/bugfixes/harness-http-call-limit/2026-10-20-delegated-run-limit.md).

## State, compatibility and isolation

Default runtime cache is process-local, created only on explicit access. Existing backend constructors, HTTP routes and session schemas remain compatible. No implicit identity authorization or distributed lease is added. Injected service objects never appear in public serialized memory fields. Existing connection configuration fields retain their serialization behavior; callers must treat those fields as sensitive and must not log or publish them. No cloud operations are needed for verification.

## Verification and change record

CON-1 maps to tests/cloud/test_harness_app_embedding.py and existing HTTP tests. CON-2/CON-3 map to tests/test_short_term_memory.py, covering injection, serialization, conflicts, existing local/SQLite behavior, callbacks, exact lookup, exceptions and cancellation. Commands and evidence are in the linked PRD. Targeted guarantees have passed the linked PRD checks; broader delivery requirements remain pending.
