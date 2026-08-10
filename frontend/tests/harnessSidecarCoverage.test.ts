import { describe, expect, it } from "vitest";
import {
  HARNESS_SIDECAR_OPTION_IDS,
  HARNESS_SIDECAR_OPTIONS,
  HARNESS_SIDECAR_PROFILES,
  harnessIntentFromOptimizations,
  harnessProfileDefaultOptimizations,
  harnessSidecarProfileLabel,
  harnessSidecarOptionLabel,
  releaseDraftFromDebugVariant,
  selectedHarnessProfile,
  selectedHarnessOptimizations,
} from "../src/create/harnessSidecarOptions";
import { emptyDraft } from "../src/create/types";

describe("Studio Harness Sidecar metadata options", () => {
  it("publishes the five capabilities integrated by this Studio release", () => {
    expect(HARNESS_SIDECAR_OPTION_IDS).toEqual([
      "context_engine",
      "compressor",
      "verifier",
      "long_run_control",
      "mcp_resilience",
    ]);
    expect(HARNESS_SIDECAR_OPTIONS.map((item) => item.displayName)).toEqual([
      "上下文治理",
      "上下文与结果压缩",
      "回答校验与修复",
      "Goal任务控制",
      "MCP 稳定性治理",
    ]);
    expect(HARNESS_SIDECAR_OPTIONS.at(-1)?.description).toContain(
      "默认包含 SQL 只读保护",
    );
  });

  it("publishes custom first and the concrete ops scenario after it", () => {
    expect(HARNESS_SIDECAR_PROFILES.map((profile) => profile.id)).toEqual([
      "default",
      "ops",
    ]);
    expect(HARNESS_SIDECAR_PROFILES.map((profile) => profile.displayName)).toEqual([
      "自定义",
      "运维场景",
    ]);
    expect(harnessProfileDefaultOptimizations("default")).toEqual([]);
    expect(harnessProfileDefaultOptimizations("ops")).toEqual([
      "context_engine",
      "compressor",
      "verifier",
      "long_run_control",
      "mcp_resilience",
    ]);
    expect(HARNESS_SIDECAR_PROFILES.at(-1)?.autoAddedComponents).toEqual([
      "sql_readonly",
    ]);
    expect(
      harnessProfileDefaultOptimizations(
        "unsupported" as Parameters<
          typeof harnessProfileDefaultOptimizations
        >[0],
      ),
    ).toEqual([]);
  });

  it("turns a selection into metadata without runtime identity", () => {
    expect(harnessIntentFromOptimizations(["verifier"])).toEqual({
      enabled: true,
      profile: "default",
      componentOverrides: {
        context_engine: false,
        compressor: false,
        verifier: true,
        long_run_control: false,
        mcp_resilience: false,
      },
    });
  });

  it("keeps the empty selection disabled", () => {
    expect(harnessIntentFromOptimizations([])).toMatchObject({
      enabled: false,
    });
  });

  it("preserves the selected profile in public intent metadata", () => {
    expect(
      harnessIntentFromOptimizations(
        harnessProfileDefaultOptimizations("ops"),
        "ops",
      ),
    ).toMatchObject({
      enabled: true,
      profile: "ops",
      componentOverrides: { mcp_resilience: true },
    });
  });

  it("materializes ordinary and ops release drafts with model fallback", () => {
    const ordinaryDraft = {
      ...emptyDraft(),
      modelName: "ordinary-model",
      description: "ordinary description",
      instruction: "ordinary instruction",
    };
    const ordinaryRelease = releaseDraftFromDebugVariant(ordinaryDraft, {
      modelName: "",
      description: ordinaryDraft.description,
      instruction: ordinaryDraft.instruction,
      profile: "default",
      optimizations: [],
    });
    expect(ordinaryRelease.modelName).toBe("ordinary-model");
    expect(ordinaryRelease.harnessSidecar).toMatchObject({
      enabled: false,
      profile: "default",
    });

    const opsRelease = releaseDraftFromDebugVariant(ordinaryDraft, {
      modelName: "ops-model",
      description: "ops description",
      instruction: "ops instruction",
      profile: "ops",
      optimizations: harnessProfileDefaultOptimizations("ops"),
    });
    expect(opsRelease).toMatchObject({
      modelName: "ops-model",
      description: "ops description",
      instruction: "ops instruction",
      harnessSidecar: {
        enabled: true,
        profile: "ops",
        componentOverrides: { mcp_resilience: true },
      },
    });
  });

  it("derives selected options from Draft metadata", () => {
    expect(selectedHarnessOptimizations(emptyDraft())).toEqual([]);
    expect(selectedHarnessProfile(emptyDraft())).toBe("default");
    expect(
      selectedHarnessOptimizations({
        ...emptyDraft(),
        harnessSidecar: harnessIntentFromOptimizations([
          "compressor",
          "mcp_resilience",
        ]),
      }),
    ).toEqual(["compressor", "mcp_resilience"]);
    expect(
      selectedHarnessProfile({
        ...emptyDraft(),
        harnessSidecar: harnessIntentFromOptimizations(
          harnessProfileDefaultOptimizations("ops"),
          "ops",
        ),
      }),
    ).toBe("ops");
  });

  it("maps known labels and preserves unknown runtime-only ids", () => {
    expect(harnessSidecarProfileLabel("default")).toBe("自定义");
    expect(harnessSidecarProfileLabel("ops")).toBe("运维场景");
    expect(harnessSidecarProfileLabel("unknown")).toBe("unknown");
    expect(harnessSidecarOptionLabel("long_run_control")).toBe("Goal任务控制");
    expect(harnessSidecarOptionLabel("sql_readonly")).toBe("sql_readonly");
  });
});
