import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const require = createRequire(import.meta.url);

async function importComponent() {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(
      "../src/ui/builtin-tools/BrowserUseStatusBar.tsx",
      import.meta.url,
    ))],
    bundle: true,
    external: ["react", "react-i18next", "i18next"],
    format: "cjs",
    platform: "node",
    write: false,
  });
  const module = { exports: {} };
  Function("require", "module", "exports", result.outputFiles[0].text)(
    require,
    module,
    module.exports,
  );
  return module.exports.BrowserUseStatusBar;
}

async function renderCard(Component, props) {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const i18nextModule = require("i18next");
  const i18next = (i18nextModule.default ?? i18nextModule).createInstance();
  const conversation = JSON.parse(readFileSync(new URL(
    "../src/i18n/resources/zh-CN/conversation.json",
    import.meta.url,
  ), "utf8"));
  await i18next.init({
    lng: "zh-CN",
    fallbackLng: "zh-CN",
    resources: { "zh-CN": { conversation } },
  });
  const { I18nextProvider } = require("react-i18next");
  return renderToStaticMarkup(React.createElement(
    I18nextProvider,
    { i18n: i18next },
    React.createElement(Component, props),
  ));
}

test("renders an actionable approval card without exposing token or digest", async () => {
  const Component = await importComponent();
  const html = await renderCard(Component, {
    state: {
      decision: "mount",
      reasonCode: "PUBLIC_WEB_TASK",
      browserLocation: "cloud",
      riskLevel: "high",
      approval: "required",
      phase: "approval_required",
      actionApproval: {
        approvalId: "approval-opaque",
        actionDigest: "a".repeat(64),
        actionSummary: "发布公告",
        targetOrigin: "https://example.com",
        riskLevel: "high",
        expiresAt: "2026-09-15T12:00:00Z",
        capabilityVersion: "browser-action-approval-v1",
      },
    },
    onApprove: () => {},
    onCancel: () => {},
    onModify: () => {},
  });

  assert.match(html, /发布公告/);
  assert.match(html, /https:\/\/example\.com/);
  assert.match(html, />确认执行</);
  assert.match(html, />取消</);
  assert.match(html, />修改内容</);
  assert.doesNotMatch(html, /approval-opaque/);
  assert.doesNotMatch(html, new RegExp("a{64}"));
});

test("shows planned controls and locks environment changes after context starts", async () => {
  const Component = await importComponent();
  const baseState = {
    decision: "mount",
    reasonCode: "PUBLIC_WEB_TASK",
    browserLocation: "cloud",
    riskLevel: "read_only",
    approval: "not_required",
  };
  const planned = await renderCard(Component, {
    state: { ...baseState, phase: "planned" },
    onSuppress: () => {},
    onSwitchLocation: () => {},
    onStop: () => {},
  });
  assert.match(planned, />本轮不用浏览器</);
  assert.match(planned, />改用本地浏览器</);
  assert.match(planned, />停止</);

  const browsing = await renderCard(Component, {
    state: { ...baseState, phase: "browsing", requestId: "call-1" },
    onSuppress: () => {},
    onSwitchLocation: () => {},
    onStop: () => {},
  });
  assert.doesNotMatch(browsing, />本轮不用浏览器</);
  assert.doesNotMatch(browsing, />改用本地浏览器</);
  assert.match(browsing, />停止</);
});

test("wires Browser controls through the conversation and consumes one-shot policy", () => {
  const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  const blocks = readFileSync(
    new URL("../src/ui/Blocks.tsx", import.meta.url),
    "utf8",
  );
  const studioConversation = readFileSync(
    new URL(
      "../src/components/ai-app/ConversationFlow/StudioConversation.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  for (const callback of [
    "onBrowserSuppress",
    "onBrowserSwitchLocation",
    "onBrowserStop",
  ]) {
    assert.match(blocks, new RegExp(callback));
    assert.match(studioConversation, new RegExp(callback));
    assert.match(app, new RegExp(callback));
  }
  assert.match(app, /browserRunPolicyBySessionRef/);
  assert.match(app, /suppressedTools:\s*browserRunPolicy\?\.suppressedTools/);
  assert.match(
    app,
    /browserApproval\?\.browserLocationOverride\s*\?\?\s*browserRunPolicy\?\.browserLocationOverride/,
  );
  assert.match(app, /browserRunPolicyBySessionRef\.current\.delete\(sid\)/);
});
