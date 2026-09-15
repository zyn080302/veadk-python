import { useTranslation } from "react-i18next";

import type {
  BrowserActionApproval,
  BrowserUseLocation,
  BrowserUseRunState,
} from "./browserUseRun";
import { browserUseCanSwitchLocation } from "./browserUseRun";

export interface BrowserUseStatusBarProps {
  state: BrowserUseRunState;
  busy?: boolean;
  onApprove?: (approval: BrowserActionApproval) => void;
  onCancel?: (approval: BrowserActionApproval) => void;
  onModify?: (approval: BrowserActionApproval) => void;
  onSuppress?: () => void;
  onSwitchLocation?: (location: BrowserUseLocation) => void;
  onStop?: () => void;
}

function BrowserUseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
      <path d="M3.5 8.5h17" />
      <path d="m9.2 15.5 2-5 1.7 3 3.2.8-6.9 1.2Z" />
    </svg>
  );
}

export function BrowserUseStatusBar({
  state,
  busy = false,
  onApprove,
  onCancel,
  onModify,
  onSuppress,
  onSwitchLocation,
  onStop,
}: BrowserUseStatusBarProps) {
  const { t } = useTranslation("conversation");
  if (
    state.decision === "no_tool"
    && !["USER_DISABLED", "TOOL_SUPPRESSED", "AUTO_POLICY_DISABLED"].includes(
      state.reasonCode,
    )
  ) return null;

  const location = state.browserLocation
    ? t(`browserUse.location.${state.browserLocation}`)
    : "";
  const title = state.decision === "mount"
    ? state.phase === "cancelled"
      ? t("browserUse.cancelled")
      : t("browserUse.enabled", { location })
    : state.decision === "unavailable"
      ? t("browserUse.unavailable")
      : t("browserUse.skipped");
  const actionApproval = state.phase === "approval_required"
    ? state.actionApproval
    : undefined;
  const approvalPending = actionApproval
    && (state.approvalResolution ?? "pending") === "pending";
  const canSwitchLocation = browserUseCanSwitchLocation(state);
  const canControlRun = state.decision === "mount"
    && (state.phase === "planned" || state.phase === "browsing");
  const switchLocation: BrowserUseLocation = state.browserLocation === "local"
    ? "cloud"
    : "local";
  const phaseLabel = state.controlResolution
    ? t(`browserUse.controlResolution.${state.controlResolution}`)
    : t(`browserUse.phase.${state.phase}`);

  return (
    <section
      className={`browser-use-status browser-use-status--${state.phase}`}
      aria-live="polite"
      aria-label={title}
    >
      <span className="browser-use-status__icon"><BrowserUseIcon /></span>
      <span className="browser-use-status__content">
        <span className="browser-use-status__title">{title}</span>
        <span className="browser-use-status__phase">
          {phaseLabel}
        </span>
      </span>
      <details className="browser-use-status__details">
        <summary>{t("browserUse.details")}</summary>
        <dl>
          <div>
            <dt>{t("browserUse.environment")}</dt>
            <dd>{location || t("browserUse.notSelected")}</dd>
          </div>
          <div>
            <dt>{t("browserUse.reason")}</dt>
            <dd>{state.reasonCode}</dd>
          </div>
        </dl>
      </details>
      {canControlRun ? (
        <div
          className="browser-use-status__controls"
          role="group"
          aria-label={t("browserUse.controls.label")}
        >
          {state.phase === "planned" ? (
            <button
              type="button"
              className="browser-use-status__control-button"
              onClick={onSuppress}
              disabled={!onSuppress}
            >
              {t("browserUse.controls.suppress")}
            </button>
          ) : null}
          {canSwitchLocation ? (
            <button
              type="button"
              className="browser-use-status__control-button"
              onClick={() => onSwitchLocation?.(switchLocation)}
              disabled={!onSwitchLocation}
            >
              {t("browserUse.controls.switch", {
                location: t(`browserUse.location.${switchLocation}`),
              })}
            </button>
          ) : null}
          <button
            type="button"
            className="browser-use-status__control-button browser-use-status__control-button--stop"
            onClick={onStop}
            disabled={!onStop}
          >
            {t("browserUse.controls.stop")}
          </button>
        </div>
      ) : null}
      {actionApproval ? (
        <div
          className="browser-use-status__approval"
          role="group"
          aria-label={t("browserUse.approval.title")}
        >
          <strong>{t("browserUse.approval.title")}</strong>
          <dl>
            <div>
              <dt>{t("browserUse.approval.action")}</dt>
              <dd>{actionApproval.actionSummary}</dd>
            </div>
            <div>
              <dt>{t("browserUse.approval.target")}</dt>
              <dd>{actionApproval.targetOrigin}</dd>
            </div>
          </dl>
          {approvalPending ? (
            <div className="browser-use-status__approval-actions">
              <button
                type="button"
                className="browser-use-status__approval-button"
                onClick={() => onModify?.(actionApproval)}
                disabled={busy || !onModify}
              >
                {t("browserUse.approval.modify")}
              </button>
              <button
                type="button"
                className="browser-use-status__approval-button"
                onClick={() => onCancel?.(actionApproval)}
                disabled={busy || !onCancel}
              >
                {t("browserUse.approval.cancel")}
              </button>
              <button
                type="button"
                className="browser-use-status__approval-button browser-use-status__approval-button--primary"
                onClick={() => onApprove?.(actionApproval)}
                disabled={busy || !onApprove}
              >
                {t("browserUse.approval.confirm")}
              </button>
            </div>
          ) : (
            <p className="browser-use-status__approval-resolution">
              {t(`browserUse.approval.${state.approvalResolution}`)}
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}
