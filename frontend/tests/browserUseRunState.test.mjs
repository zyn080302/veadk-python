import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const result = await build({
  entryPoints: [
    fileURLToPath(
      new URL("../src/ui/builtin-tools/browserUseRun.ts", import.meta.url),
    ),
  ],
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  write: false,
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(
  result.outputFiles[0].contents,
).toString("base64")}`;
const {
  applyBrowserUseProgress,
  browserApprovalRunPolicy,
  browserUseCanSwitchLocation,
  browserUseNextRunPolicy,
  parseBrowserUsePlanEvent,
  parseBrowserUseProgress,
  resolveBrowserUseControl,
} = await import(moduleUrl);
const blocksResult = await build({
  entryPoints: [fileURLToPath(new URL("../src/blocks.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  write: false,
});
const blocksModuleUrl = `data:text/javascript;base64,${Buffer.from(
  blocksResult.outputFiles[0].contents,
).toString("base64")}`;
const { applyEvent, emptyAcc } = await import(blocksModuleUrl);

test("parses only the public Browser ToolPlan projection", () => {
  const event = parseBrowserUsePlanEvent({
    studioEvent: "studio.tool_plan",
    payload: {
      decision: "mount",
      reasonCode: "PUBLIC_WEB_TASK",
      browserLocation: "cloud",
      riskLevel: "read_only",
      approval: "not_required",
      endpoint: "http://janus.internal/a2a",
      contextId: "private-context",
    },
  });

  assert.deepEqual(event, {
    decision: "mount",
    reasonCode: "PUBLIC_WEB_TASK",
    browserLocation: "cloud",
    riskLevel: "read_only",
    approval: "not_required",
    phase: "planned",
  });
  assert.equal(parseBrowserUsePlanEvent({ studioEvent: "other" }), null);
});

test("reduces Browser A2A progress without accepting arbitrary tool metadata", () => {
  const started = parseBrowserUseProgress({
    veadkStudioToolProgress: {
      toolName: "browser_use",
      requestId: "call-1",
      phase: "browser_a2a_started",
      browserLocation: "local",
      endpoint: "private",
    },
  });
  assert.deepEqual(started, {
    requestId: "call-1",
    phase: "browsing",
    browserLocation: "local",
  });
  assert.equal(
    parseBrowserUseProgress({
      veadkStudioToolProgress: {
        toolName: "current_time",
        phase: "browser_a2a_started",
      },
    }),
    null,
  );

  const state = applyBrowserUseProgress(
    {
      decision: "mount",
      reasonCode: "LOCAL_BROWSER_STATE",
      browserLocation: "local",
      riskLevel: "read_only",
      approval: "not_required",
      phase: "planned",
    },
    started,
  );
  assert.equal(state.phase, "browsing");
  assert.equal(state.browserLocation, "local");
});

test("projects ToolPlan and progress into one Browser status block", () => {
  let acc = applyEvent(emptyAcc(), {
    studioEvent: "studio.tool_plan",
    payload: {
      decision: "mount",
      reasonCode: "PUBLIC_WEB_TASK",
      browserLocation: "cloud",
      riskLevel: "read_only",
      approval: "not_required",
    },
  });
  acc = applyEvent(acc, {
    partial: true,
    content: {
      parts: [{
        partMetadata: {
          veadkStudioToolProgress: {
            toolName: "browser_use",
            requestId: "call-1",
            phase: "browser_a2a_completed",
            browserLocation: "cloud",
            status: "completed",
          },
        },
      }],
    },
  });

  assert.equal(acc.blocks.length, 1);
  assert.equal(acc.blocks[0].kind, "browser-use");
  assert.equal(acc.blocks[0].state.phase, "completed");
  assert.equal(acc.blocks[0].state.requestId, "call-1");
});

test("keeps the opaque approval only in the private Browser progress state", () => {
  const progress = parseBrowserUseProgress({
    veadkStudioToolProgress: {
      toolName: "browser_use",
      requestId: "call-approval",
      phase: "browser_approval_required",
      browserLocation: "cloud",
      approval: {
        approvalId: "approval-opaque",
        actionDigest: "a".repeat(64),
        actionSummary: "发布公告",
        targetOrigin: "https://example.com",
        riskLevel: "high",
        expiresAt: "2026-09-15T12:00:00Z",
        capabilityVersion: "browser-action-approval-v1",
        internalEndpoint: "must-be-dropped",
      },
    },
  });

  assert.deepEqual(progress, {
    requestId: "call-approval",
    phase: "approval_required",
    browserLocation: "cloud",
    actionApproval: {
      approvalId: "approval-opaque",
      actionDigest: "a".repeat(64),
      actionSummary: "发布公告",
      targetOrigin: "https://example.com",
      riskLevel: "high",
      expiresAt: "2026-09-15T12:00:00Z",
      capabilityVersion: "browser-action-approval-v1",
    },
  });
  assert.equal(
    parseBrowserUseProgress({
      veadkStudioToolProgress: {
        toolName: "browser_use",
        phase: "browser_approval_required",
        approval: {
          approvalId: "approval-opaque",
          actionDigest: "invalid",
        },
      },
    }),
    null,
  );

  const state = applyBrowserUseProgress(
    {
      decision: "mount",
      reasonCode: "PUBLIC_WEB_TASK",
      browserLocation: "cloud",
      riskLevel: "high",
      approval: "required",
      phase: "browsing",
    },
    progress,
  );
  assert.deepEqual(browserApprovalRunPolicy(state), {
    approvalId: "approval-opaque",
    browserLocationOverride: "cloud",
  });
});

test("builds one-shot Browser controls without mutating an active ToolPlan", () => {
  const planned = {
    decision: "mount",
    reasonCode: "PUBLIC_WEB_TASK",
    browserLocation: "cloud",
    riskLevel: "read_only",
    approval: "not_required",
    phase: "planned",
  };

  assert.equal(browserUseCanSwitchLocation(planned), true);
  assert.equal(
    browserUseCanSwitchLocation({ ...planned, requestId: "call-1" }),
    false,
  );
  assert.equal(
    browserUseCanSwitchLocation({ ...planned, phase: "browsing" }),
    false,
  );
  assert.deepEqual(browserUseNextRunPolicy("suppressed"), {
    suppressedTools: ["browser_use"],
  });
  assert.deepEqual(browserUseNextRunPolicy("switch_local"), {
    browserLocationOverride: "local",
  });
  assert.deepEqual(browserUseNextRunPolicy("switch_cloud"), {
    browserLocationOverride: "cloud",
  });
  assert.equal(browserUseNextRunPolicy("stopped"), null);
  assert.deepEqual(resolveBrowserUseControl(planned, "suppressed"), {
    ...planned,
    phase: "skipped",
    reasonCode: "TOOL_SUPPRESSED",
    controlResolution: "suppressed",
  });
  assert.deepEqual(resolveBrowserUseControl(planned, "switch_local"), {
    ...planned,
    phase: "cancelled",
    reasonCode: "USER_SWITCHED_BROWSER_LOCATION",
    controlResolution: "switch_local",
  });
});
