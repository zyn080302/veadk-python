# Harness session resource compatibility

[中文](2026-10-15-session-resources.zh.md)

Status: implementation authorized by the user request to adapt AI OPS to the latest Harness App Server, verify Studio Skill/MCP updates and then publish the image. Revision: 2026-10-15.

## Evidence and scope
The real SDK drops static SkillToolset entries unconditionally. With shell disabled, a configured Skill has no usable reader. The host also rejects valid studio-prefixed read-only Skill tools. Existing MCP-only success does not establish combined Skill/MCP success. Fix the actual bridge and host validation; do not special-case the test prompt.

## Requirements and design
- FR-1: shell-disabled invocations expose configured SkillToolset tools through normal ADK execution. Shell-enabled defaults keep native materialized Skills. Resolve the existing shell_enabled configuration at the bridge; do not change tool filtering, callbacks or permissions.
- FR-2: the optional AIOpsExtension composes a fresh host Agent each invocation. Latest Harness owns model/configuration selection and session persistence. No new controller or public HTTP protocol.
- FR-3: successive turns in one session can replace model, Skill and MCP, including empty selections. Each turn retains its snapshot; other sessions are isolated. Revoked tools are absent from later declarations and executors; history remains available.
- FR-4: read-only Skill tool names with the host prefix are accepted; script execution remains rejected. No shell, credential disclosure, private Core source or prompt in SDK.

## Files, tasks and acceptance
T-1: tests/runtime/codex/test_codex_runtime.py and real-runtime tests demonstrate FR-1 failure before repair, then pass. T-2: runtime/codex/tools_bridge.py and runtime.py repair FR-1. T-3: optional extension host integration and static/dynamic combined tests cover FR-2/3/4 in the private Host repo. Existing full pytest and native smoke gates include the new regression.

## Risks and verification
Preserve ordinary SDK behavior; test both shell states. Toolset open/close follows existing invocation cleanup. Cancellation/errors must propagate with resources closed. Do not persist credentials in evidence. Offline tests, native local protocol tests and account 5663 Studio/cloud acceptance are distinct. Real acceptance includes Skill-only method marker, an actual read-only MCP receipt, same-session replacement/clear, model replacement and retained history. Customer runtimes are excluded. Image publication follows successful gates and combined acceptance.

## Review
Self-review completed: existing user authorization covers implementation; no separate approval needed. Bilingual scope and identifiers match. Component impact: aiops-extension CON-6 documents fresh composition and host ownership; native bridge behavior changes only when shell is disabled. No dependency on private Core is added to the default SDK.

Verification (2026-10-15): full SDK regression passed (7,128 passed, 50 skipped, 4 expected failures); real Codex process smoke passed (12 passed, 2 database-configuration skips). Installed Core and independent Host gates passed, including four native session-resource tests. Studio configuration removal and combined restoration passed through the actual editor and saved configuration readback. Cloud image publication and six real Studio turns completed on the designated test Runtime; no customer runtime was changed. Fixed Skill+MCP produced a method-marker Skill receipt and an actual read-only MCP receipt. The same session then accepted the second model setting with temporary Skill+MCP, removed MCP while retaining a working Skill reader, cleared all temporary resources, and recalled prior facts without new tool calls. A fresh session did not inherit those facts or mounts. Original Agent resources were restored through the editor and read back; only the two task sessions were deleted and confirmed absent, and passive browser instrumentation was removed. Model selection is evidenced by the real Studio request settings and native regression; no upstream response_model field was available in SSE. Empty configurations may still mention unavailable native default Skill names; no corresponding execution tools were registered. Anonymous registry verification covered manifest/config and one byte from every layer, not a complete anonymous cold pull.

## Distribution compatibility addendum

The installed Core startup gate found that the extension branch omitted previously shipped veadk.aiops.harness, services and py.typed. Restore the same public adapters and offline regressions from reviewed commit 8fd2eff5, preserving source startup and legacy imports without adding private reasoning, default dependencies or global patches. Managed templates still use the latest independent Host. Self-review confirms this SDK upgrade completeness repair remains within the authorized scope.

## Installed-consumer compatibility review
The full Core gate reproduced loss of two shipped, opt-in Studio contracts: generated MCP overlays must invoke an existing Agent-owned acknowledgement handler instead of adding a second bare toolset; introspection must advertise instructionExtension only when the host explicitly sets the extension marker. Restore these small generic hooks without importing Core or changing ordinary Agent behavior. Add SDK offline regression and retain the Core consumer gate. A separate Core test assumed ADK cards always expose instructions; ADK 2.7.1 no longer does so. Compare the wrapped ordinary card against the actual upstream builder, while retaining private-card nondisclosure assertions. This is a dependency-aware invariant, not an excuse to skip the test. Self-review: within existing compatibility authorization; no cloud write before gates.
