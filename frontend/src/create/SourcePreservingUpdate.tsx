import { type ComponentType, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Rocket } from "lucide-react";
import { deployAgentkitProject } from "../adk/client";
import { isDeploymentStatusUnconfirmedError } from "../adk/deploymentStatus";
import { Button } from "@openai/apps-sdk-ui/components/Button";
import { ResourceDetail, ResourcePageHeader } from "../ui/ResourceCollection";
import { SkillSourcePicker } from "../ui/SkillSourcePicker";
import { CodeBrowserDialog } from "../ui/CodeBrowserDialog";
import type { DeploymentTaskUpdate } from "../ui/ProjectPreview";
import type { CustomCreateProps } from "./CustomCreate";
import type { AgentDraft, McpTool, SelectedSkill } from "./types";
import {
  type McpConfigurationConflict,
  mcpConfigurationConflict,
  prepareMcpAuth,
  removedConfiguredMcpEnvKeys,
  sourcePreservingMcpSecretValues,
} from "./mcpAuth";
import "./SourcePreservingUpdate.css";

type McpEditor = ComponentType<{
  tools: McpTool[];
  conflict: McpConfigurationConflict | null;
  showConflict: boolean;
  onChange: (tools: McpTool[]) => void;
}>;

/** No general deployment environment or transient credentials in stored drafts. */
function portableDraft(draft: AgentDraft): AgentDraft {
  const clean = (node: AgentDraft): AgentDraft => ({
    ...node,
    deployment: undefined,
    subAgents: node.subAgents.map(clean),
    ...(node.workflow
      ? {
          workflow: {
            ...node.workflow,
            nodes: node.workflow.nodes.map((n) => ({
              ...n,
              agent: clean(n.agent),
            })),
          },
        }
      : {}),
  });
  return clean(prepareMcpAuth(draft).draft);
}

function mapNodes(
  root: AgentDraft,
  transform: (node: AgentDraft) => AgentDraft,
): AgentDraft {
  const node = transform(root);
  return {
    ...node,
    subAgents: node.subAgents.map((child) => mapNodes(child, transform)),
    ...(node.workflow
      ? {
          workflow: {
            ...node.workflow,
            nodes: node.workflow.nodes.map((n) => ({
              ...n,
              agent: mapNodes(n.agent, transform),
            })),
          },
        }
      : {}),
  };
}

export function SourcePreservingUpdate({
  initialDraft,
  deploymentTarget: target,
  cloudProvider = "volcengine",
  onBack,
  onDraftChange,
  onDeploymentTaskChange,
  onDeploymentStarted,
  onDeploymentComplete,
  workspaceDraftId,
  McpEditor,
}: CustomCreateProps & { McpEditor: McpEditor }) {
  const { t } = useTranslation("create");
  const [draft, setDraft] = useState(initialDraft!);
  const [editing, setEditing] = useState<{
    agent: string;
    folder: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");
  const submitting = useRef(false);
  const unconfirmed = useRef(false);
  const initialSnapshot = useRef(JSON.stringify(portableDraft(initialDraft!)));
  const lastSnapshot = useRef(initialSnapshot.current);
  const snapshot = JSON.stringify(portableDraft(draft));
  const notifyDraft = useRef(onDraftChange);
  notifyDraft.current = onDraftChange;
  useEffect(() => {
    if (snapshot === lastSnapshot.current) return;
    lastSnapshot.current = snapshot;
    notifyDraft.current?.(
      JSON.parse(snapshot),
      snapshot !== initialSnapshot.current,
    );
  }, [snapshot]);
  const nodes: AgentDraft[] = [];
  mapNodes(draft, (node) => {
    nodes.push(node);
    return node;
  });
  const conflict = mcpConfigurationConflict(draft);
  const editingNode = nodes.find((node) => node.name === editing?.agent);
  const editingSkill = editingNode?.selectedSkills?.find(
    (skill) => skill.folder === editing?.folder,
  );
  const patch = (name: string, values: Partial<AgentDraft>) => {
    setDraft((current) =>
      mapNodes(current, (node) =>
        node.name === name ? { ...node, ...values } : node,
      ),
    );
    setError("");
  };
  const publish = async () => {
    if (submitting.current || finished || unconfirmed.current) return;
    if (!target?.etag || !Number.isInteger(target.currentVersion)) {
      setError(t("sourcePreserving.reloadRequired"));
      return;
    }
    if (conflict) {
      setError(t("sourcePreserving.mcpConflict"));
      return;
    }
    if (
      nodes.some((node) =>
        node.mcpTools?.some((tool) => {
          if (tool.transport !== "http") return false;
          try {
            const url = new URL(tool.url || "");
            return (
              !["http:", "https:"].includes(url.protocol) ||
              Boolean(url.username || url.password || url.search || url.hash)
            );
          } catch {
            return true;
          }
        }),
      )
    ) {
      setError(t("sourcePreserving.invalidMcp"));
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError("");
    const task: DeploymentTaskUpdate = {
      id: crypto.randomUUID(),
      draftId: workspaceDraftId,
      agentName: draft.name,
      runtimeName: target.name,
      runtimeId: target.runtimeId,
      region: target.region,
      startedAt: Date.now(),
      status: "running",
      phase: "prepare",
      label: t("sourcePreserving.publishing"),
      agentDraft: portableDraft(draft),
    };
    onDeploymentTaskChange?.(task);
    onDeploymentStarted?.(task);
    try {
      const result = await deployAgentkitProject(
        draft.name,
        [],
        { region: target.region, projectName: "default" },
        {
          taskId: task.id,
          runtimeId: target.runtimeId,
          runtimeName: target.name,
          appName: target.appName,
          editMode: "source-preserving",
          updateEtag: target.etag,
          baseRuntimeVersion: target.currentVersion,
          draft: portableDraft(draft),
          harnessSidecar: draft.harnessSidecar,
          mcpSecretValues: sourcePreservingMcpSecretValues(draft),
          removeRuntimeEnvKeys: removedConfiguredMcpEnvKeys(
            target.configuredMcpEnvKeys ?? [],
            draft,
          ),
          onStage: (stage) => {
            setProgress(stage.message);
            onDeploymentTaskChange?.({
              ...task,
              phase: stage.phase,
              message: stage.message,
              pct: stage.pct,
              ...(stage.buildLog ? { buildLog: stage.buildLog } : {}),
            });
          },
        },
      );
      setFinished(true);
      setProgress(t("sourcePreserving.complete"));
      onDeploymentTaskChange?.({
        ...task,
        status: "success",
        phase: "complete",
        label: t("sourcePreserving.complete"),
        pct: 100,
      });
      await onDeploymentComplete?.(result);
    } catch (cause) {
      unconfirmed.current = isDeploymentStatusUnconfirmedError(cause);
      const message =
        cause instanceof Error ? cause.message : t("sourcePreserving.failed");
      setError(message);
      onDeploymentTaskChange?.({
        ...task,
        status: "error",
        statusUnconfirmed: unconfirmed.current,
        label: t("sourcePreserving.failed"),
        message,
      });
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };
  return (
    <ResourceDetail>
      <div className="source-update-scroll">
        <div className="source-update">
          <div className="source-update-back">
            <Button
              color="secondary"
              variant="ghost"
              size="md"
              pill={false}
              disabled={busy}
              onClick={onBack}
            >
              <ArrowLeft size={16} />
              {t("sourcePreserving.back")}
            </Button>
          </div>
          <ResourcePageHeader
            title={t("sourcePreserving.title", { name: target?.name })}
            description={t("sourcePreserving.description")}
          />
          <h2 className="source-update-section-title">
            {t("sourcePreserving.assets")}
          </h2>
          <fieldset
            disabled={busy || finished}
            className="source-update-fields"
          >
            {nodes.map((node) => (
              <section key={node.name} className="source-update-agent">
                {nodes.length > 1 && <h2>{node.name}</h2>}
                <h3>{t("traditional.tools.mcp")}</h3>
                <McpEditor
                  tools={node.mcpTools ?? []}
                  conflict={conflict}
                  showConflict={Boolean(error)}
                  onChange={(mcpTools) => patch(node.name, { mcpTools })}
                />
                <h3>{t("sourcePreserving.skills")}</h3>
                <SkillSourcePicker
                  selected={node.selectedSkills ?? []}
                  cloudProvider={cloudProvider}
                  disabled={busy || finished}
                  onChange={(selectedSkills) =>
                    patch(node.name, { selectedSkills })
                  }
                  onEdit={(skill) =>
                    setEditing({ agent: node.name, folder: skill.folder })
                  }
                />
              </section>
            ))}
          </fieldset>
          {progress && (
            <p role="status" aria-live="polite">
              {progress}
            </p>
          )}
          {error && (
            <p role="alert" className="source-update-error">
              {error}
            </p>
          )}
          {editingSkill?.localFiles && (
            <CodeBrowserDialog
              key={`${editing?.agent}/${editing?.folder}`}
              open
              project={{
                name: editingSkill.name,
                files: editingSkill.localFiles,
              }}
              onClose={() => setEditing(null)}
              onChange={(project) => {
                const next: SelectedSkill = {
                  ...editingSkill,
                  source: "local",
                  localFiles: project.files,
                };
                patch(editingNode!.name, {
                  selectedSkills: editingNode!.selectedSkills!.map((skill) =>
                    skill.folder === next.folder ? next : skill,
                  ),
                });
              }}
            />
          )}

          <section className="source-update-release" aria-label="Runtime">
            <div>
              <strong>{target?.name}</strong>
              <p>
                {target?.region} · v{target?.currentVersion}
              </p>
            </div>
            <Button
              color="primary"
              size="lg"
              pill={false}
              loading={busy}
              disabled={busy || finished || unconfirmed.current}
              onClick={() => void publish()}
            >
              <Rocket size={16} />
              {t(
                busy
                  ? "sourcePreserving.publishing"
                  : "sourcePreserving.publish",
              )}
            </Button>
          </section>
        </div>
      </div>
    </ResourceDetail>
  );
}
