export type BrowserUseDecision = "mount" | "no_tool" | "unavailable";
export type BrowserUseLocation = "local" | "cloud";
export type BrowserUsePhase =
  | "planned"
  | "browsing"
  | "completed"
  | "failed"
  | "approval_required"
  | "cancelled"
  | "skipped"
  | "unavailable";
export type BrowserUseControlResolution =
  | "suppressed"
  | "switch_local"
  | "switch_cloud"
  | "stopped";
export type BrowserApprovalResolution =
  | "pending"
  | "confirmed"
  | "cancelled"
  | "editing";

export interface BrowserActionApproval {
  approvalId: string;
  actionDigest: string;
  actionSummary: string;
  targetOrigin: string;
  riskLevel: string;
  expiresAt: string;
  capabilityVersion: "browser-action-approval-v1";
}

export interface BrowserUseRunState {
  decision: BrowserUseDecision;
  reasonCode: string;
  browserLocation?: BrowserUseLocation;
  riskLevel: string;
  approval: string;
  phase: BrowserUsePhase;
  requestId?: string;
  actionApproval?: BrowserActionApproval;
  approvalResolution?: BrowserApprovalResolution;
  controlResolution?: BrowserUseControlResolution;
}

export interface BrowserUseProgress {
  requestId?: string;
  phase: BrowserUsePhase;
  browserLocation?: BrowserUseLocation;
  actionApproval?: BrowserActionApproval;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function location(value: unknown): BrowserUseLocation | undefined {
  return value === "local" || value === "cloud" ? value : undefined;
}

function actionApproval(value: unknown): BrowserActionApproval | undefined {
  const approval = record(value);
  if (!approval) return undefined;
  const required = [
    "approvalId",
    "actionDigest",
    "actionSummary",
    "targetOrigin",
    "riskLevel",
    "expiresAt",
    "capabilityVersion",
  ] as const;
  if (required.some((key) =>
    typeof approval[key] !== "string" || !approval[key].trim()
  )) return undefined;
  const approvalId = String(approval.approvalId).trim();
  const actionDigest = String(approval.actionDigest).trim();
  const capabilityVersion = String(approval.capabilityVersion).trim();
  if (
    approvalId.length > 512
    || !/^[a-f0-9]{64}$/i.test(actionDigest)
    || capabilityVersion !== "browser-action-approval-v1"
  ) return undefined;
  return {
    approvalId,
    actionDigest,
    actionSummary: String(approval.actionSummary).trim(),
    targetOrigin: String(approval.targetOrigin).trim(),
    riskLevel: String(approval.riskLevel).trim(),
    expiresAt: String(approval.expiresAt).trim(),
    capabilityVersion,
  };
}

export function parseBrowserUsePlanEvent(
  value: unknown,
): BrowserUseRunState | null {
  const event = record(value);
  if (event?.studioEvent !== "studio.tool_plan") return null;
  const payload = record(event.payload);
  if (!payload) return null;
  const decision = payload.decision;
  if (
    decision !== "mount"
    && decision !== "no_tool"
    && decision !== "unavailable"
  ) return null;
  if (
    typeof payload.reasonCode !== "string"
    || typeof payload.riskLevel !== "string"
    || typeof payload.approval !== "string"
  ) return null;
  const browserLocation = location(payload.browserLocation);
  if (decision === "mount" && browserLocation === undefined) return null;
  return {
    decision,
    reasonCode: payload.reasonCode,
    ...(browserLocation ? { browserLocation } : {}),
    riskLevel: payload.riskLevel,
    approval: payload.approval,
    phase:
      decision === "mount"
        ? "planned"
        : decision === "unavailable"
          ? "unavailable"
          : "skipped",
  };
}

export function parseBrowserUseProgress(
  partMetadata: unknown,
): BrowserUseProgress | null {
  const metadata = record(partMetadata);
  const progress = record(metadata?.veadkStudioToolProgress);
  if (!progress || progress.toolName !== "browser_use") return null;
  const phase = progress.phase;
  let normalizedPhase: BrowserUsePhase;
  if (phase === "browser_a2a_started") normalizedPhase = "browsing";
  else if (phase === "browser_a2a_completed") {
    normalizedPhase = progress.status === "error" ? "failed" : "completed";
  } else if (phase === "browser_approval_required") {
    normalizedPhase = "approval_required";
  } else if (phase === "browser_a2a_failed") normalizedPhase = "failed";
  else return null;
  const requestId =
    typeof progress.requestId === "string" && progress.requestId
      ? progress.requestId
      : undefined;
  const browserLocation = location(progress.browserLocation);
  const approval = normalizedPhase === "approval_required"
    ? actionApproval(progress.approval)
    : undefined;
  if (normalizedPhase === "approval_required" && approval === undefined) {
    return null;
  }
  return {
    ...(requestId ? { requestId } : {}),
    phase: normalizedPhase,
    ...(browserLocation ? { browserLocation } : {}),
    ...(approval ? { actionApproval: approval } : {}),
  };
}

export function applyBrowserUseProgress(
  state: BrowserUseRunState,
  progress: BrowserUseProgress,
): BrowserUseRunState {
  return {
    ...state,
    phase: progress.phase,
    ...(progress.browserLocation
      ? { browserLocation: progress.browserLocation }
      : {}),
    ...(progress.requestId ? { requestId: progress.requestId } : {}),
    ...(progress.actionApproval
      ? {
          actionApproval: progress.actionApproval,
          approvalResolution: "pending" as const,
        }
      : {}),
  };
}

export function resolveBrowserUseApproval(
  state: BrowserUseRunState,
  approvalId: string,
  resolution: Exclude<BrowserApprovalResolution, "pending">,
): BrowserUseRunState {
  if (state.actionApproval?.approvalId !== approvalId) return state;
  return { ...state, approvalResolution: resolution };
}

export function browserApprovalRunPolicy(
  state: BrowserUseRunState,
): {
  approvalId: string;
  browserLocationOverride: BrowserUseLocation;
} | null {
  if (
    state.phase !== "approval_required"
    || (state.approvalResolution ?? "pending") !== "pending"
    || !state.actionApproval
    || !state.browserLocation
  ) return null;
  return {
    approvalId: state.actionApproval.approvalId,
    browserLocationOverride: state.browserLocation,
  };
}

export function browserUseCanSwitchLocation(
  state: BrowserUseRunState,
): boolean {
  return state.decision === "mount"
    && state.phase === "planned"
    && state.requestId === undefined;
}

export function browserUseNextRunPolicy(
  resolution: BrowserUseControlResolution,
): {
  suppressedTools?: readonly ["browser_use"];
  browserLocationOverride?: BrowserUseLocation;
} | null {
  if (resolution === "suppressed") {
    return { suppressedTools: ["browser_use"] };
  }
  if (resolution === "switch_local") {
    return { browserLocationOverride: "local" };
  }
  if (resolution === "switch_cloud") {
    return { browserLocationOverride: "cloud" };
  }
  return null;
}

export function resolveBrowserUseControl(
  state: BrowserUseRunState,
  resolution: BrowserUseControlResolution,
): BrowserUseRunState {
  return {
    ...state,
    phase: resolution === "suppressed" ? "skipped" : "cancelled",
    reasonCode: resolution === "suppressed"
      ? "TOOL_SUPPRESSED"
      : resolution === "stopped"
        ? "USER_CANCELLED"
        : "USER_SWITCHED_BROWSER_LOCATION",
    controlResolution: resolution,
  };
}
