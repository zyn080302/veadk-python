import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { createRequire } from "node:module";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

async function loadTypeScriptModule(relativePath, format = "esm") {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(relativePath, import.meta.url))],
    bundle: true,
    format,
    platform: "node",
    target: "node20",
    write: false,
  });
  if (format === "esm") {
    const source = Buffer.from(result.outputFiles[0].contents).toString("base64");
    return import(`data:text/javascript;base64,${source}`);
  }
  const directory = mkdtempSync(join(tmpdir(), "veadk-browser-migration-test-"));
  const bundle = join(directory, "module.cjs");
  try {
    writeFileSync(bundle, result.outputFiles[0].contents);
    return createRequire(import.meta.url)(bundle);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

const {
  migrateLegacyBrowserAutomationDraft,
  normalizeDraft,
} = await loadTypeScriptModule("../src/create/normalizeDraft.ts");
const { draftToYaml, yamlToDraft } = await loadTypeScriptModule(
  "../src/create/configYaml.ts",
  "cjs",
);

const source = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const customCreateSource = source("../src/create/CustomCreate.tsx");
const catalogSource = source("../src/create/veadkCatalog.ts");
const codegenSource = source("../../veadk/cli/generated_agent_codegen.py");
const plannerSource = source("../../veadk/cli/generated_agent_planner.py");

test("new creation and generation paths expose no static Browser Automation", () => {
  assert.doesNotMatch(
    customCreateSource,
    /traditional\.tools\.browser|builtinTools\.includes\("browser_automation"\)|cw-browser-location/,
  );
  assert.doesNotMatch(catalogSource, /browser_automation|JanusRemoteA2AAgent/);
  assert.doesNotMatch(codegenSource, /browserAutomation|JanusRemoteA2AAgent/);
  assert.doesNotMatch(plannerSource, /browser_automation|browserLocation/);
});

test("legacy Browser Automation is removed recursively without choosing a location", () => {
  const base = normalizeDraft({
    name: "legacy-root",
    builtinTools: ["web_search"],
    subAgents: [{ name: "legacy-child", builtinTools: ["link_reader"] }],
  });
  const legacy = {
    ...base,
    builtinTools: ["web_search", "browser_automation"],
    browserAutomation: { browserLocation: "unexpected-location" },
    subAgents: [
      {
        ...base.subAgents[0],
        builtinTools: ["link_reader", "browser_automation"],
        browserAutomation: { browserLocation: "cloud" },
      },
    ],
  };

  const migrated = migrateLegacyBrowserAutomationDraft(legacy);

  assert.equal(migrated.migrated, true);
  assert.deepEqual(migrated.draft.builtinTools, ["web_search"]);
  assert.equal("browserAutomation" in migrated.draft, false);
  assert.deepEqual(migrated.draft.subAgents[0].builtinTools, ["link_reader"]);
  assert.equal("browserAutomation" in migrated.draft.subAgents[0], false);
  assert.deepEqual(legacy.builtinTools, ["web_search", "browser_automation"]);
});

test("legacy YAML imports are stripped and exports cannot recreate static Janus", () => {
  const restored = yamlToDraft(`
name: legacy-yaml
builtinTools:
  - web_search
  - browser_automation
browserAutomation:
  browserLocation: cloud
`);

  assert.deepEqual(restored.builtinTools, ["web_search"]);
  assert.equal("browserAutomation" in restored, false);
  const exported = draftToYaml(restored);
  assert.doesNotMatch(exported, /browserAutomation|browser_automation|Janus/);
});

test("legacy migration is visible once in the existing creation banner", () => {
  assert.match(customCreateSource, /legacyBrowserAutomationMigrated/);
  assert.match(customCreateSource, /traditional\.browserMigration\.notice/);
  assert.match(customCreateSource, /className="cw-banner"/);
});
