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
  harnessIntentFromOptimizations,
  harnessIntentFromRuntimeEnvs,
  normalizeHarnessSidecarIntent,
  harnessSidecarProviderNotice,
  harnessProfileDefaultOptimizations,
  releaseDraftFromDebugVariant,
  selectedHarnessModelProxyOptimizations,
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
        context_engine: false,
        compressor: true,
        verifier: false,
        long_run_control: false,
        mcp_resilience: true,
      },
    },
  });

  assert.equal(draft.harnessSidecar.profile, "ops");
  assert.deepEqual(draft.harnessSidecar.componentOverrides, {
    context_engine: true,
    compressor: false,
    verifier: true,
    long_run_control: true,
    mcp_resilience: true,
  });
  const restored = yamlToDraft(draftToYaml(draft));
  assert.equal(restored.harnessSidecar.profile, "ops");
  assert.deepEqual(
    restored.harnessSidecar.componentOverrides,
    draft.harnessSidecar.componentOverrides,
  );
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

test("supports localized YAML header comments", () => {
  const yaml = draftToYaml(normalizeDraft({ name: "localized" }), {
    heading: "VeADK agent structure configuration",
    importHint: "Reload this file from Import YAML on the Create Agent page.",
  });

  assert.match(yaml, /^# VeADK agent structure configuration$/m);
  assert.match(yaml, /^# Reload this file from Import YAML on the Create Agent page\.$/m);
  assert.doesNotMatch(yaml, /[\u3400-\u9fff]/u);
});

test("uses this Studio release's integrated optimization metadata", () => {
  assert.match(harnessOptionsSource, /HARNESS_SIDECAR_OPTIONS/);
  assert.match(harnessOptionsSource, /HARNESS_SIDECAR_OPTION_GROUPS/);
  assert.match(harnessOptionsSource, /HARNESS_SIDECAR_PROFILES/);
  assert.match(harnessOptionsSource, /traditional\.optimization\.profiles\.default\.label/);
  assert.match(harnessOptionsSource, /traditional\.optimization\.profiles\.ops\.label/);
  assert.match(harnessOptionsSource, /traditional\.optimization\.options\.\$\{id\}\.label/);
  assert.match(harnessOptionsSource, /traditional\.optimization\.options\.\$\{id\}\.description/);
  assert.doesNotMatch(customCreateSource, /getHarnessSidecarCatalog/);
  assert.doesNotMatch(customCreateSource, /resolveHarnessSidecarSelection/);
  assert.doesNotMatch(harnessOptionsSource, /sql_readonly\s*:/);
  assert.match(customCreateSource, /function HarnessOptimizationWorkspace/);
  assert.match(customCreateSource, /traditional\.optimization\.scenario/);
  assert.doesNotMatch(customCreateSource, /不启用|value="none"/);
  assert.match(customCreateSource, /traditional\.optimization\.options\.\$\{item\.id\}\.label/);
  assert.match(customCreateSource, /onProfileChange/);
  assert.match(customCreateSource, /harnessProfileDefaultOptimizations/);
});

test("fails fast with a clear BytePlus Sidecar notice without blocking ordinary agents", () => {
  assert.equal(harnessSidecarProviderNotice("volcengine"), null);
  assert.match(
    harnessSidecarProviderNotice("byteplus"),
    /not available/,
  );
  assert.match(
    customCreateSource,
    /providerDraft\.harnessSidecar\?\.enabled && harnessProviderNotice/,
  );
  assert.match(
    customCreateSource,
    /selected && harnessProviderNotice[\s\S]*?setBuildErr\(harnessProviderNotice\)/,
  );
  assert.match(
    customCreateSource,
    /unavailableMessage=\{harnessProviderNotice\}/,
  );
});

test("derives Model Proxy dependencies from the selected optimization catalog", () => {
  const draft = normalizeDraft({
    name: "dependency-agent",
    harnessSidecar: {
      componentOverrides: {
        context_engine: true,
        compressor: false,
        verifier: true,
        long_run_control: false,
        mcp_resilience: true,
      },
    },
  });

  assert.deepEqual(selectedHarnessModelProxyOptimizations(draft), [
    "context_engine",
    "verifier",
  ]);
});

test("places the Harness optimization page immediately before environment setup", () => {
  assert.match(
    customCreateSource,
    /type WorkspaceMode =[\s\S]*?\| "validate"[\s\S]*?\| "optimize"[\s\S]*?\| "environment"[\s\S]*?\| "publish";/,
  );
  assert.match(
    customCreateSource,
    /\{ id: "build", label: "traditional\.workspace\.modes\.build" \},\s*\{ id: "validate", label: "traditional\.workspace\.modes\.validate" \},\s*\{ id: "optimize", label: "traditional\.workspace\.modes\.optimize" \},\s*\{ id: "environment", label: "traditional\.workspace\.modes\.environment" \},\s*\{ id: "publish", label: "traditional\.workspace\.modes\.publish" \}/,
  );
  assert.match(customCreateSource, /optimize:\s*"traditional\.workspace\.titles\.optimize"/);
  assert.doesNotMatch(customCreateSource, /为您的智能体选择一些优化项/);
  assert.ok(
    customCreateSource.indexOf('{workspaceMode === "validate"') <
      customCreateSource.indexOf('{workspaceMode === "optimize"'),
  );
  assert.ok(
    customCreateSource.indexOf('{workspaceMode === "optimize"') <
      customCreateSource.indexOf('{workspaceMode === "environment"'),
  );
  assert.match(
    customCreateSource,
    /const handleWorkspaceChange = async[\s\S]*?nextMode === "optimize"[\s\S]*?openOptimization\(\)/,
  );
});

test("materializes an ordinary project snapshot into one ops release draft", () => {
  const ordinaryDraft = normalizeDraft({
    name: "ordinary-agent",
    description: "ordinary description",
    instruction: "ordinary instruction",
    harnessSidecar: {
      profile: "ops",
      componentOverrides: Object.fromEntries(
        harnessProfileDefaultOptimizations("ops").map((id) => [id, true]),
      ),
    },
  });
  const selectedVariant = {
    modelName: "doubao-seed-1-6-250615",
    description: "ops description",
    instruction: "ops instruction",
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
    compressor: false,
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
    /const openOptimization = async[\s\S]*?setWorkspaceMode\("optimize"\)/,
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
  });

  assert.equal(releaseDraft.harnessSidecar, undefined);
});

test("carries the selected variant into debug generation and deployment", () => {
  assert.match(
    customCreateSource,
    /const updateHarnessOptimization = \([\s\S]*?harnessSidecar: harnessIntentFromOptimizations\(/,
  );
  assert.doesNotMatch(customCreateSource, /harnessSidecar: undefined/);
  assert.match(clientSource, /body: JSON\.stringify\(\{\s*draft,/);
  assert.match(clientSource, /harnessSidecar: opts\?\.harnessSidecar/);
  assert.match(
    customCreateSource,
    /description: draft\.description,[\s\S]*?harnessSidecar: draft\.harnessSidecar/,
  );
  assert.match(configYamlSource, /harnessSidecar/);
});

test("marks a running variant stale when the draft optimization selection changes", () => {
  assert.match(
    customCreateSource,
    /const currentDebugSnapshot = useMemo\([\s\S]*?debugSnapshotKey\(providerDraft/,
  );
  assert.match(
    customCreateSource,
    /const stale = Boolean\([\s\S]*?runtimeSnapshot !==[\s\S]*?debugVariantSnapshot\(draftSnapshot, variant\)/,
  );
  assert.match(customCreateSource, /traditional\.debug\.configurationChanged/);
});

test("applies scenario defaults while allowing an empty custom selection", () => {
  assert.match(
    customCreateSource,
    /const updateHarnessOptimizationProfile = \([\s\S]*?harnessProfileDefaultOptimizations\(profile\)/,
  );
  assert.doesNotMatch(customCreateSource, /!harnessOptimizationProfile/);
  assert.match(harnessOptionsSource, /traditional\.optimization\.profiles\.default\.description/);
  assert.match(customCreateSource, /traditional\.optimization\.releaseScenario/);
  assert.match(
    customCreateSource,
    /harnessOptimizations\.map\(\(id\) =>\s*t\(`traditional\.optimization\.options\.\$\{id\}\.label`\)/,
  );
  assert.match(
    customCreateSource,
    /harnessOptimizationProfile === "ops"\s*\? "default"\s*: harnessOptimizationProfile/,
  );
});

test("treats checkbox changes as metadata and defers checks to runtime actions", () => {
  assert.match(
    customCreateSource,
    /const updateHarnessOptimization = \([\s\S]*?setDraft\(\(current\) =>/,
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

const summaryPolicy = Object.freeze({
  mode: "auto",
  summary_model: "deepseek-v4-flash-ga-260731",
  context_window: 1024000,
  input_limit: 900000,
  output_reserve: 32768,
  summary_context_window: 1024000,
  summary_input_limit: 900000,
  media_token_reserve: 1200,
  safety_margin: 1024,
  keep_recent_turns: 2,
  summary_max_tokens: 2048,
  max_summary_calls: 2,
  target_ratio: 0.6,
  trigger_ratio: 0.8,
  summary_trigger_ratio: 0.95,
  summary_timeout_seconds: 30,
  summary_time_budget_seconds: 60,
});

function summaryIntent(components = ["compressor"]) {
  return {
    ...harnessIntentFromOptimizations(components),
    globalContext: { ...summaryPolicy },
  };
}

test("preserves and copies the complete summary policy in intent normalization", () => {
  const source = summaryIntent();
  const normalized = normalizeHarnessSidecarIntent(source);
  assert.deepEqual(normalized.globalContext, summaryPolicy);
  assert.notEqual(normalized.globalContext, source.globalContext);
  normalized.globalContext.summary_model = "other-summary";
  assert.equal(source.globalContext.summary_model, summaryPolicy.summary_model);
});

test("preserves summary policy across Draft and YAML without changing analysis model", () => {
  const draft = normalizeDraft({ name: "summary-agent", modelName: "analysis-pro",
    harnessSidecar: summaryIntent() });
  assert.deepEqual(draft.harnessSidecar.globalContext, summaryPolicy);
  const restored = yamlToDraft(draftToYaml(draft));
  assert.deepEqual(restored.harnessSidecar.globalContext, summaryPolicy);
  assert.equal(restored.modelName, "analysis-pro");
});

test("exports summary policy even when the input Draft has not been normalized", () => {
  const draft = normalizeDraft({ name: "summary-agent" });
  draft.harnessSidecar = summaryIntent();
  assert.deepEqual(yamlToDraft(draftToYaml(draft)).harnessSidecar.globalContext,
    summaryPolicy);
});

test("keeps disabled summary settings through YAML without enabling compression", () => {
  const draft = normalizeDraft({ name: "summary-agent", harnessSidecar: summaryIntent([]) });
  const restored = yamlToDraft(draftToYaml(draft));
  assert.equal(restored.harnessSidecar?.enabled, false);
  assert.equal(restored.harnessSidecar.componentOverrides.compressor, false);
  assert.deepEqual(restored.harnessSidecar.globalContext, summaryPolicy);
});

for (const enabled of [true, false]) {
  test(`restores Runtime summary policy with Sidecar enabled=${enabled}`, () => {
    const restored = harnessIntentFromRuntimeEnvs([
      { key: "HARNESS_SIDECAR_ENABLED", value: String(enabled) },
      { key: "HARNESS_SIDECAR_COMPONENT_OVERRIDES", value: '{"compressor":true}' },
      { key: "HARNESS_GLOBAL_CONTEXT_JSON", value: JSON.stringify(summaryPolicy) },
    ]);
    assert.deepEqual(restored.globalContext, summaryPolicy);
    assert.equal(restored.enabled, enabled);
    assert.equal(restored.componentOverrides.compressor, enabled);
  });
}

test("keeps explicit summary settings when the editor changes optimization selections", () => {
  const disabled = harnessIntentFromOptimizations([], "default", summaryPolicy);
  assert.equal(disabled.enabled, false);
  assert.deepEqual(disabled.globalContext, summaryPolicy);
  const enabled = harnessIntentFromOptimizations(["compressor"], "default", disabled.globalContext);
  assert.deepEqual(enabled.globalContext, summaryPolicy);
  assert.notEqual(enabled.globalContext, disabled.globalContext);
});

test("does not invent a summary policy for legacy Drafts or Runtime snapshots", () => {
  assert.equal(normalizeDraft({ name: "legacy" }).harnessSidecar, undefined);
  assert.equal(normalizeHarnessSidecarIntent(harnessIntentFromOptimizations(["compressor"]))
    .globalContext, undefined);
  assert.equal(harnessIntentFromRuntimeEnvs([
    { key: "HARNESS_SIDECAR_ENABLED", value: "true" },
    { key: "HARNESS_MODEL_PROXY_ENABLED", value: "true" },
  ]).globalContext, undefined);
});

const invalidSummaryPolicies = [
  { ...summaryPolicy, input_limit: true },
  { ...summaryPolicy, summary_max_tokens: 127 },
  { ...summaryPolicy, max_summary_calls: 5 },
  { ...summaryPolicy, keep_recent_turns: 1.5 },
  { ...summaryPolicy, summary_timeout_seconds: Infinity },
  { ...summaryPolicy, trigger_ratio: NaN },
  { ...summaryPolicy, target_ratio: 0.9 },
  { ...summaryPolicy, context_window: 32769 },
  { ...summaryPolicy, summary_context_window: 2048 },
  { ...summaryPolicy, summary_model: "unsafe model INPUT_MUST_NOT_ECHO" },
  { ...summaryPolicy, summary_model: "summary-model\n" },
  { ...summaryPolicy, mode: "off" },
  { ...summaryPolicy, thinking: "enabled" },
  { ...summaryPolicy, unknown_field: "INPUT_MUST_NOT_ECHO" },
  [summaryPolicy],
  "INPUT_MUST_NOT_ECHO",
];
for (const [index, policy] of invalidSummaryPolicies.entries()) {
  test(`rejects invalid summary configuration ${index} without echoing input`, () => {
    assert.throws(() => normalizeDraft({ name: "invalid", harnessSidecar: {
      ...summaryIntent(), globalContext: policy,
    } }), (error) => error instanceof Error &&
      error.message === "Invalid Studio global context configuration");
  });
}

test("rejects malformed Runtime policy instead of silently replacing it with defaults", () => {
  assert.throws(() => harnessIntentFromRuntimeEnvs([
    { key: "HARNESS_SIDECAR_ENABLED", value: "true" },
    { key: "HARNESS_GLOBAL_CONTEXT_JSON", value: "INPUT_MUST_NOT_ECHO" },
  ]), { message: "Invalid Studio global context configuration" });
});
