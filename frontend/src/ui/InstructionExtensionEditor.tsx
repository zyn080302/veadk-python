import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../components/primitives/Button";
import MarkdownPromptEditor from "../create/MarkdownPromptEditor";
import {
  instructionExtension,
  InstructionExtensionError,
  type InstructionExtension,
  type InstructionExtensionTarget,
} from "../adk/client";
import { TextShimmer } from "./text-shimmer/TextShimmer";
import "./InstructionExtensionEditor.css";

/** Mount with an app/endpoint key so a switched Agent cannot inherit an edit. */
export function InstructionExtensionEditor({ appName, target }: {
  appName: string;
  target?: InstructionExtensionTarget;
}) {
  const { t } = useTranslation("workspaceTools");
  const [snapshot, setSnapshot] = useState<InstructionExtension | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const operation = useRef<AbortController | null>(null);
  const composing = useRef(false);
  const publishing = snapshot?.publication === "pending" || snapshot?.publication === "unknown";
  const remote = snapshot?.storage === "runtime_env";

  async function load() {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const value = await instructionExtension(appName, undefined, controller.signal, target);
      if (!controller.signal.aborted) {
        setSnapshot(value);
        setText(value.instruction);
      }
    } catch {
      if (!controller.signal.aborted) setError("loadError");
    } finally {
      if (!controller.signal.aborted) {
        operation.current = null;
        setBusy(false);
      }
    }
  }

  useEffect(() => {
    void load();
    return () => operation.current?.abort();
  }, [appName, target?.runtimeId, target?.region]);

  async function save() {
    if (!snapshot || publishing || operation.current || composing.current || invalid) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setSaved(false);
    setError("");
    try {
      const value = await instructionExtension(appName, {
        instruction: text, revision: snapshot.revision,
      }, controller.signal, target);
      if (!controller.signal.aborted) {
        setSnapshot(value);
        setSaved(true);
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause instanceof InstructionExtensionError && cause.status === 409
          ? "conflict" : remote ? "publishError" : "saveError");
      }
    } finally {
      if (!controller.signal.aborted) {
        operation.current = null;
        setBusy(false);
      }
    }
  }

  const invalid = text.length > 65536 || (remote && new TextEncoder().encode(text).length > 65536);
  return <section className="topo-module-card instruction-extension" aria-label={t("instructionExtension.title")}>
    <p className="topo-description">{t("instructionExtension.priority")}</p>
    {!snapshot && busy && <TextShimmer as="span">{t("instructionExtension.loading")}</TextShimmer>}
    {snapshot && <div
      role="group"
      aria-label={t("instructionExtension.title")}
      onCompositionStart={() => { composing.current = true; }}
      onCompositionEnd={() => { composing.current = false; }}
    >
      <MarkdownPromptEditor value={text} invalid={invalid} readOnly={busy || publishing} onChange={(value) => {
        setText(value); setSaved(false);
      }} />
    </div>}
    {invalid && <p role="alert">{t(remote ? "instructionExtension.envTooLong" : "instructionExtension.tooLong")}</p>}
    {error && <p role="alert">{t(`instructionExtension.${error}`)}</p>}
    {publishing && <p role="status">{t(snapshot?.publication === "unknown"
      ? "instructionExtension.publishUnknown" : "instructionExtension.publishPending")}</p>}
    {!publishing && saved && text === snapshot?.instruction && <p role="status">{t("instructionExtension.saved")}</p>}
    <div className="instruction-extension-actions">
      <Button size="compact" variant="outline" disabled={busy} onClick={() => void load()}>
        {t("instructionExtension.reload")}
      </Button>
      <Button size="compact" loading={busy} disabled={!snapshot || publishing || invalid || text === snapshot.instruction || error === "conflict" || error === "publishError"} onClick={() => void save()}>
        {t(remote ? "instructionExtension.saveAndPublish" : "instructionExtension.save")}
      </Button>
    </div>
  </section>;
}
