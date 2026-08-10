import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

async function loadTypeScriptModule(relativePath) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(relativePath, import.meta.url))],
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    write: false,
  });
  const source = Buffer.from(result.outputFiles[0].contents).toString("base64");
  return import(`data:text/javascript;base64,${source}`);
}

async function loadCommonJsTypeScriptModule(relativePath) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(relativePath, import.meta.url))],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "node20",
    write: false,
  });
  const directory = mkdtempSync(join(tmpdir(), "veadk-sidecar-test-"));
  const bundle = join(directory, "module.cjs");
  try {
    writeFileSync(bundle, result.outputFiles[0].contents);
    return createRequire(import.meta.url)(bundle);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

const { normalizeDraft } = await loadTypeScriptModule(
  "../src/create/normalizeDraft.ts",
);
const {
  harnessProfileDefaultOptimizations,
  releaseDraftFromDebugVariant,
} = await loadTypeScriptModule("../src/create/harnessSidecarOptions.ts");
const { draftToYaml, yamlToDraft } = await loadCommonJsTypeScriptModule(
  "../src/create/configYaml.ts",
);
const customCreateSource = readFileSync(
  new URL("../src/create/CustomCreate.tsx", import.meta.url),
  "utf8",
);
const harnessOptionsSource = readFileSync(
  new URL("../src/create/harnessSidecarOptions.ts", import.meta.url),
  "utf8",
);
const clientSource = readFileSync(
  new URL("../src/adk/client.ts", import.meta.url),
  "utf8",
);
const configYamlSource = readFileSync(
  new URL("../src/create/configYaml.ts", import.meta.url),
  "utf8",
);

test("normalizes the five-option intent and derives enabled", () => {
  const draft = normalizeDraft({
    name: "agent",
    harnessSidecar: {
      enabled: false,
      profile: "default",
      componentOverrides: {
        context_engine: true,
        sql_readonly: true,
      },
    },
  });

  assert.equal(draft.harnessSidecar.enabled, true);
  assert.deepEqual(draft.harnessSidecar.componentOverrides, {
    context_engine: true,
    compressor: false,
    verifier: false,
    long_run_control: false,
    mcp_resilience: false,
  });
  assert.equal("sql_readonly" in draft.harnessSidecar.componentOverrides, false);
});

test("normalizes and round-trips the ops profile", () => {
  const draft = normalizeDraft({
    name: "ops-agent",
    harnessSidecar: {
      profile: "ops",
      componentOverrides: {
        context_engine: true,
        compressor: true,
        verifier: true,
        long_run_control: true,
        mcp_resilience: true,
      },
    },
  });

  assert.equal(draft.harnessSidecar.profile, "ops");
  const restored = yamlToDraft(draftToYaml(draft));
  assert.equal(restored.harnessSidecar.profile, "ops");
  assert.equal(restored.harnessSidecar.componentOverrides.mcp_resilience, true);
});

test("round-trips selected options in YAML and omits the unselected default", () => {
  const plainYaml = draftToYaml(normalizeDraft({ name: "plain" }));
  assert.doesNotMatch(plainYaml, /harnessSidecar|harness_sidecar/);

  const selected = normalizeDraft({
    name: "selected",
    harnessSidecar: {
      componentOverrides: {
        verifier: true,
        mcp_resilience: true,
      },
    },
  });
  const yaml = draftToYaml(selected);
  const restored = yamlToDraft(yaml);

  assert.equal(restored.harnessSidecar.enabled, true);
  assert.deepEqual(restored.harnessSidecar.componentOverrides, {
    context_engine: false,
    compressor: false,
    verifier: true,
    long_run_control: false,
    mcp_resilience: true,
  });
  assert.doesNotMatch(yaml, /sql_readonly|bytedance-agentkit-harness-sidecar/);
});

test("uses this Studio release's integrated optimization metadata", () => {
  assert.match(harnessOptionsSource, /HARNESS_SIDECAR_OPTIONS/);
  assert.match(harnessOptionsSource, /HARNESS_SIDECAR_PROFILES/);
  assert.match(harnessOptionsSource, /自定义/);
  assert.match(harnessOptionsSource, /运维场景/);
  assert.match(harnessOptionsSource, /Goal任务控制/);
  assert.match(harnessOptionsSource, /默认包含 SQL 只读保护/);
  assert.doesNotMatch(customCreateSource, /getHarnessSidecarCatalog/);
  assert.doesNotMatch(customCreateSource, /resolveHarnessSidecarSelection/);
  assert.doesNotMatch(harnessOptionsSource, /sql_readonly\s*:/);
  assert.match(customCreateSource, /当前版本已集成/);
  assert.match(customCreateSource, /优化场景/);
  assert.match(customCreateSource, /aria-label="优化场景"/);
  assert.doesNotMatch(customCreateSource, /不启用|value="none"/);
  assert.match(customCreateSource, /<strong>\{profile\.displayName\}<\/strong>/);
  assert.match(customCreateSource, /onProfileChange/);
  assert.match(customCreateSource, /harnessProfileDefaultOptimizations/);
});

test("materializes an ordinary project snapshot into one ops release draft", () => {
  const ordinaryDraft = normalizeDraft({
    name: "ordinary-agent",
    description: "ordinary description",
    instruction: "ordinary instruction",
  });
  const selectedVariant = {
    modelName: "doubao-seed-1-6-250615",
    description: "ops description",
    instruction: "ops instruction",
    profile: "ops",
    optimizations: harnessProfileDefaultOptimizations("ops"),
  };

  const releaseDraft = releaseDraftFromDebugVariant(
    ordinaryDraft,
    selectedVariant,
  );

  assert.equal(releaseDraft.description, selectedVariant.description);
  assert.equal(releaseDraft.instruction, selectedVariant.instruction);
  assert.equal(releaseDraft.harnessSidecar.profile, "ops");
  assert.deepEqual(releaseDraft.harnessSidecar.componentOverrides, {
    context_engine: true,
    compressor: true,
    verifier: true,
    long_run_control: true,
    mcp_resilience: true,
  });
  assert.match(
    customCreateSource,
    /const materializePublishRelease = async[\s\S]*?releaseDraftFromDebugVariant\(providerDraft, releaseVariant\)[\s\S]*?generateAgentProject\(codegenDraft\(releaseDraft\)\)[\s\S]*?setDraft\(releaseDraft\)[\s\S]*?setProject\(generated\)/,
  );
  assert.match(
    customCreateSource,
    /const openPublishPreview = async[\s\S]*?materializePublishRelease\(variantId\)/,
  );
  assert.match(
    customCreateSource,
    /const handleWorkspaceChange = async[\s\S]*?nextMode === "publish"[\s\S]*?materializePublishRelease\(\)/,
  );
  assert.doesNotMatch(
    customCreateSource,
    /if \(project\) setWorkspaceMode\("publish"\)/,
  );
  assert.match(
    customCreateSource,
    /description: draft\.description,[\s\S]*?harnessSidecar: draft\.harnessSidecar/,
  );
});

test("preserves the ordinary zero-component release draft", () => {
  const ordinaryDraft = normalizeDraft({
    name: "ordinary-agent",
    description: "ordinary description",
    instruction: "ordinary instruction",
  });
  const releaseDraft = releaseDraftFromDebugVariant(ordinaryDraft, {
    modelName: ordinaryDraft.modelName,
    description: ordinaryDraft.description,
    instruction: ordinaryDraft.instruction,
    profile: "default",
    optimizations: [],
  });

  assert.equal(releaseDraft.harnessSidecar.enabled, false);
  assert.equal(releaseDraft.harnessSidecar.profile, "default");
  assert.deepEqual(releaseDraft.harnessSidecar.componentOverrides, {
    context_engine: false,
    compressor: false,
    verifier: false,
    long_run_control: false,
    mcp_resilience: false,
  });
});

test("carries the selected variant into debug generation and deployment", () => {
  assert.match(
    customCreateSource,
    /harnessSidecar:\s*harnessIntentFromOptimizations\([\s\S]*?variant\.optimizations,[\s\S]*?variant\.profile/,
  );
  assert.match(clientSource, /body: JSON\.stringify\(\{\s*draft,/);
  assert.match(clientSource, /harnessSidecar: opts\?\.harnessSidecar/);
  assert.match(
    customCreateSource,
    /description: draft\.description,[\s\S]*?harnessSidecar: draft\.harnessSidecar/,
  );
  assert.match(configYamlSource, /harnessSidecar/);
});

test("marks a running variant stale when its optimization selection changes", () => {
  assert.match(
    customCreateSource,
    /function debugVariantSnapshot\([\s\S]*?profile:\s*variant\.profile,[\s\S]*?optimizations:\s*variant\.optimizations/,
  );
  assert.match(
    customCreateSource,
    /const stale = Boolean\([\s\S]*?runtimeSnapshot !==[\s\S]*?debugVariantSnapshot\(draftSnapshot, variant\)/,
  );
  assert.match(customCreateSource, /配置已变更，请重新启动此环境/);
});

test("applies scenario defaults while allowing an empty custom selection", () => {
  assert.match(
    customCreateSource,
    /const updateDebugVariantProfile = \([\s\S]*?harnessProfileDefaultOptimizations\(profile\)/,
  );
  assert.doesNotMatch(customCreateSource, /!variant\.profile/);
  assert.match(customCreateSource, /不勾选时不启动 Sidecar/);
  assert.match(customCreateSource, /优化场景：\$\{harnessSidecarProfileLabel/);
  assert.match(customCreateSource, /自动启用 SQL 只读保护/);
});

test("treats checkbox changes as metadata and defers checks to runtime actions", () => {
  assert.match(
    customCreateSource,
    /const updateDebugVariantOptimization = \([\s\S]*?patchDebugVariant\(id, \{ optimizations \}\)/,
  );
  assert.doesNotMatch(customCreateSource, /resolveHarnessOptimizationPlan/);
  assert.doesNotMatch(customCreateSource, /harnessCatalogLoading/);
  assert.match(
    customCreateSource,
    /createdRun = await createGeneratedAgentTestRun\(/,
  );
  assert.match(
    clientSource,
    /harnessSidecar: opts\?\.harnessSidecar/,
  );
});
