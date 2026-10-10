# Source-preserving deployment lifecycle

[中文版](2026-10-10-mpa-lifecycle.zh.md)

Change ID: studio-source-preserving-lifecycle | Date: 2026-10-10 | Status: implemented


## Final acceptance (2026-10-10)

This final record supersedes the pending status in the historical verification checkpoint below. AC-1 through AC-3 and FR-4: pass. The final mandatory frontend run passed 1386 Node and 72 React tests, production build and packaged assets; pre-commit passed. The normal Studio confirmation flow updated the authorized old application from V55 to V56, issued zero MPA Profile writes, and completed successfully. Reopening recovered the two Skills and five MCP references. The fresh-session Skill/MCP acceptance passed; the initial MCP parameter error was corrected by the model and remains recorded. Earlier V55 GUI failure was not relabelled successful. No cloud Studio or protected customer Agent was updated.

## Evidence and scope
The authorized old application update built and published a Ready Runtime with all four MCP credentials preserved, then ProjectPreview failed at profile_applying with mpa_operation_service_unavailable. Its Boolean(agentDraft) condition treats a recovered application draft as an MPA deployment. A source-preserving update owns Skill/MCP overlays and must not invoke MPA Profile management.

## Requirements and design
- FR-1: Pass the existing source-preserving/regenerate edit mode from CustomCreate to ProjectPreview. Explicit source-preserving updates omit MPA lifecycle stages, Profile API calls and MPA retries; successful Runtime publication completes normally.
- FR-2: Generated/new MPA deployments and regenerate updates retain Profile application, its real error handling and smoke semantics. GitHub-offloaded updates retain their existing behavior. Do not catch and suppress MPA API failures.
- FR-3: Preserve draft Skill/MCP selection, source packaging, credentials, Runtime target, publication count and ordinary API contracts. No cloud Studio or customer Agent is changed by this fix.

The existing ProjectPreview components, confirmation and global task state remain. This is a lifecycle selection correction, with no styling, inputs, new dependencies or visual component design. A single optional typed prop carries existing edit metadata; no Runtime or agent-name heuristics. Component contract: [AI OPS extension](../../../specs/aiops-extension/README.md), CON-16. The separate Vulcan/MPA workbench remains MPA-owned.

## Tasks and acceptance
- T-1 / AC-1: Render the real ProjectPreview, publish a source-preserving fixture, and assert one deploy, zero Profile calls, terminal success and no Profile progress. Record RED before editing production code.
- T-2 / AC-2: Preserve regenerate success, real Profile failure and non-MPA code-package paths. Add the component test to the mandatory npm test command.
- T-3 / AC-3: Pass frontend tests, production build, asset integrity and pre-commit. Reopen the published test Agent, perform the planned second Skill/MCP update through the GUI, and validate the new candidate and its first conversation.

## Review and authorization
The user's existing instruction authorizes completing Studio updates on the old application only and fixing the failures found during acceptance. This correction stays within that scope; it does not authorize unrelated resources. Direct review replaces unavailable review-spec: explicit edit metadata, unchanged MPA defaults, no secret transport changes, preserved errors and no duplicate cloud publish. Both languages were reviewed together. No design blocker remains.

## Verification and risks
FR-4, discovered during second-update acceptance: a complete source-preserving snapshot can have an empty static instruction when the runtime owns its dynamic prompt. Only explicit source-preserving validation may omit missingPrompt at root and child nodes; identity, description, topology, credential and MCP conflict checks remain. Creation/regeneration stays strict. Do not invent a prompt or modify runtime instructions. Exercise the actual CustomCreate validation functions before correction and retain backend immutable-instruction regressions. Direct design review confirms this is the same authorized update path with no new permissions or APIs.

Verified on 2026-10-10: the real component regression failed before the fix (1 failed, 4 passed) and passed afterwards (5 passed). The mandatory frontend gate passed (1,382 Node tests and 72 component tests), production build passed, packaged asset verification passed (113 files / 350 references), and isolated all-files pre-commit passed. Evidence: `.codex/source-lifecycle-{red,green,frontend-tests,build,assets,precommit}.log`. Live second-update acceptance remains not_run. The current published candidate remains usable; the failed GUI task is retained as failure evidence and is not relabelled successful. Skipping Profile for all structured drafts would break MPA; tests must exercise both edit modes. Cloud acceptance and final documentation remain pending.
