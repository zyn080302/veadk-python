import type {
  AgentDraft,
  HarnessSidecarIntent,
  HarnessSidecarOptionId,
  HarnessSidecarProfileId,
} from "./types";

export interface HarnessSidecarOption {
  id: HarnessSidecarOptionId;
  displayName: string;
  description: string;
}

export interface HarnessSidecarProfile {
  id: HarnessSidecarProfileId;
  displayName: string;
  description: string;
  defaultComponents: readonly HarnessSidecarOptionId[];
  autoAddedComponents: readonly string[];
}

export const HARNESS_SIDECAR_OPTIONS: readonly HarnessSidecarOption[] = [
  {
    id: "context_engine",
    displayName: "上下文治理",
    description: "治理上下文组装、任务锚定和上下文预算。",
  },
  {
    id: "compressor",
    displayName: "上下文与结果压缩",
    description: "压缩长上下文和大型工具结果，降低 Token 成本。",
  },
  {
    id: "verifier",
    displayName: "回答校验与修复",
    description: "校验证据和回答，在失败时执行修复或告警。",
  },
  {
    id: "long_run_control",
    displayName: "Goal任务控制",
    description: "管理 Goal 任务的进度、续跑和结束条件。",
  },
  {
    id: "mcp_resilience",
    displayName: "MCP 稳定性治理",
    description: "治理连接、超时、空结果、大返回和调用预算；默认包含 SQL 只读保护。",
  },
];

export const HARNESS_SIDECAR_OPTION_IDS: HarnessSidecarOptionId[] =
  HARNESS_SIDECAR_OPTIONS.map((item) => item.id);

export const HARNESS_SIDECAR_PROFILES: readonly HarnessSidecarProfile[] = [
  {
    id: "default",
    displayName: "自定义",
    description: "按需选择组件，不勾选时不启动 Sidecar。",
    defaultComponents: [],
    autoAddedComponents: [],
  },
  {
    id: "ops",
    displayName: "运维场景",
    description: "适用于运维诊断、数据库、日志和监控 MCP。",
    defaultComponents: [
      "context_engine",
      "compressor",
      "verifier",
      "long_run_control",
      "mcp_resilience",
    ],
    autoAddedComponents: ["sql_readonly"],
  },
];

export function harnessSidecarOptionLabel(id: string): string {
  return HARNESS_SIDECAR_OPTIONS.find((item) => item.id === id)?.displayName ?? id;
}

export function harnessSidecarProfileLabel(id: string): string {
  return HARNESS_SIDECAR_PROFILES.find((item) => item.id === id)?.displayName ?? id;
}

export function harnessProfileDefaultOptimizations(
  profile: HarnessSidecarProfileId,
): HarnessSidecarOptionId[] {
  const metadata = HARNESS_SIDECAR_PROFILES.find((item) => item.id === profile);
  if (!metadata) return [];
  return [...metadata.defaultComponents];
}

export function harnessIntentFromOptimizations(
  optimizations: readonly HarnessSidecarOptionId[],
  profile: HarnessSidecarProfileId = "default",
): HarnessSidecarIntent {
  const selected = new Set(optimizations);
  const intent: HarnessSidecarIntent = {
    enabled: selected.size > 0,
    profile,
    componentOverrides: Object.fromEntries(
      HARNESS_SIDECAR_OPTION_IDS.map((id) => [id, selected.has(id)]),
    ) as HarnessSidecarIntent["componentOverrides"],
  };
  return intent;
}

export interface HarnessSidecarDebugVariant {
  modelName: string;
  description: string;
  instruction: string;
  profile: HarnessSidecarProfileId;
  optimizations: readonly HarnessSidecarOptionId[];
}

export function releaseDraftFromDebugVariant(
  draft: AgentDraft,
  variant: HarnessSidecarDebugVariant,
): AgentDraft {
  return {
    ...draft,
    modelName: variant.modelName || draft.modelName,
    description: variant.description,
    instruction: variant.instruction,
    harnessSidecar: harnessIntentFromOptimizations(
      variant.optimizations,
      variant.profile,
    ),
  };
}

export function selectedHarnessProfile(
  draft: AgentDraft,
): HarnessSidecarProfileId {
  return draft.harnessSidecar?.profile ?? "default";
}

export function selectedHarnessOptimizations(
  draft: AgentDraft,
): HarnessSidecarOptionId[] {
  const overrides = draft.harnessSidecar?.componentOverrides;
  return overrides
    ? HARNESS_SIDECAR_OPTION_IDS.filter((id) => overrides[id])
    : [];
}
