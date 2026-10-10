# Studio draft storage

[中文版](README.zh.md)

- Component: studio-draft-storage; status: draft; revision: 2026-10-10.
- Scope: frontend/src/create/agentDraftStorage.ts and mcpAuth.ts; tests: frontend/tests/agentDraftStorage.test.mjs.
- Related design: [AI OPS Harness template](../../prd-spec/features/aiops-harness-template/2026-10-10-harness-template.md).

## Responsibility and interfaces
The browser stores user-scoped workspace drafts through writeWorkspaceDrafts/loadWorkspaceDrafts and sanitizes them with sanitizeAgentDraftForStorage. MCP values are transient; the backend owns credential resolution and validates Agent/name/URL identity. This component neither authenticates resources nor authorizes deployment.

## Contracts
- CON-1: Raw MCP authToken values and their deployment.envValues entries never enter serialized drafts, including child Agents and workflow nodes.
- CON-2 (proposed repair): A server-confirmed credentialConfigured=true tool retains its existing authTokenEnv when a value was hydrated for editing. Save/load/prepare preserves the reference, so a refresh does not remove authentication.
- CON-3: New or replaced transient tokens do not become stored credentials. An explicit clear removes the reference and configured marker. Do not infer a missing reference or attach another endpoint's secret.
- CON-4: prepareMcpAuth removes UI credential flags and raw token values from the deployment draft. The backend remains authoritative for reference identity, missing values and endpoint changes.

## State, persistence and failures
Version 1 localStorage payloads remain compatible. Serialization is synchronous and pure with respect to the source draft; repeated save/load is idempotent. Invalid formats and storage failures retain existing errors. Already damaged drafts cannot reconstruct deleted references: reopen the exact deployed Agent. No new logs, credential store, network calls or global mutable state.

## Verification and change record
CON-1 through CON-4 map to agentDraftStorage.test.mjs hydration/save/load/deployment tests and existing mcpAuth tests, executed by npm --prefix frontend test and the mandatory frontend Harness gate. Build and actual browser refresh/update acceptance remain separate. The 2026-10-10 repair is proposed; no live success is claimed.
