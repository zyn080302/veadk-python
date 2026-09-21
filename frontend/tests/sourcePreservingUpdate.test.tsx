// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CustomCreate } from "../src/create/CustomCreate";
import { emptyDraft } from "../src/create/types";
import { DeploymentStatusUnconfirmedError } from "../src/adk/deploymentStatus";
import { deployAgentkitProject, generateAgentProject } from "../src/adk/client";

vi.mock("../src/adk/client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  deployAgentkitProject: vi.fn(),
  generateAgentProject: vi.fn(),
  listModelApiKeys: vi.fn(async () => ({ keys: [] })),
  listModelOptions: vi.fn(async () => ({ models: [] })),
}));
const { translation } = vi.hoisted(() => ({
  translation: { t: (key: string) => key, i18n: { language: "en-US" } },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => translation,
  initReactI18next: { type: "3rdParty", init() {} },
}));
vi.mock("../src/create/AgentBuildCanvas", () => ({
  AgentBuildCanvas: () => null,
}));
// Keep real workflow/events and MCP editor. Skill file editor is covered in the native browser.
vi.mock("../src/ui/CodeBrowserDialog", () => ({
  CodeBrowserDialog: ({ project, open, onChange, onClose }: any) =>
    open ? (
      <div role="dialog">
        <textarea
          aria-label="skill file"
          value={project.files[0].content}
          onChange={(e) =>
            onChange({
              ...project,
              files: [{ ...project.files[0], content: e.target.value }],
            })
          }
        />
        <button onClick={onClose}>close file</button>
      </div>
    ) : null,
}));

let root: ReturnType<typeof createRoot>;
let host: HTMLDivElement;
const target = {
  runtimeId: "offline-runtime",
  name: "expert-runtime",
  region: "cn-beijing",
  appName: "expert",
  currentVersion: 3,
  etag: "offline-etag",
  editMode: "source-preserving" as const,
  configuredMcpEnvKeys: ["MCP_EXPERT_OLD_AUTH_TOKEN"],
};
const draft = () => ({
  ...emptyDraft("volcengine"),
  name: "expert",
  description: "expert",
  instruction: "",
  modelName: "",
  mcpTools: [
    {
      name: "lookup",
      transport: "http" as const,
      url: "https://mcp.invalid/lookup",
    },
  ],
  selectedSkills: [
    {
      source: "local" as const,
      folder: "triage",
      name: "triage",
      localFiles: [
        { path: "skills/triage/SKILL.md", content: "# original skill" },
      ],
    },
  ],
});
const button = (key: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === key || b.getAttribute("aria-label") === key,
  );
async function click(key: string) {
  const b = button(key);
  expect(b, `missing button ${key}`).toBeDefined();
  await act(async () => b!.click());
}
async function input(
  el: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype,
      "value",
    )!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function mount(overrides = {}) {
  await act(async () =>
    root.render(
      <CustomCreate
        onBack={vi.fn()}
        onCreate={vi.fn()}
        initialDraft={draft()}
        deploymentTarget={target}
        {...overrides}
      />,
    ),
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  window.matchMedia = vi
    .fn()
    .mockReturnValue({
      matches: false,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
    });
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("publishes a recovered agent with no core prompt or model key, without code generation or Runtime configuration mutations", async () => {
  vi.mocked(deployAgentkitProject).mockResolvedValue({
    runtimeId: target.runtimeId,
    runtimeName: target.name,
  } as any);
  await mount();
  // Old UI routes this agent through requiredPrompt/API-key validation and never offers this update action.
  await click("sourcePreserving.publish");
  expect(generateAgentProject).not.toHaveBeenCalled();
  expect(deployAgentkitProject).toHaveBeenCalledTimes(1);
  const [name, files, config, options] = vi.mocked(deployAgentkitProject).mock
    .calls[0];
  expect(name).toBe("expert");
  expect(files).toEqual([]);
  expect(config.region).toBe("cn-beijing");
  expect(options).toMatchObject({
    runtimeId: target.runtimeId,
    editMode: "source-preserving",
    updateEtag: target.etag,
    baseRuntimeVersion: 3,
  });
  expect(options?.draft?.instruction).toBe("");
  for (const key of [
    "envs",
    "im",
    "minInstance",
    "maxInstance",
    "authentication",
    "network",
    "sessionStorage",
  ])
    expect(options).not.toHaveProperty(key);
  expect(options?.removeRuntimeEnvKeys).not.toContain("FEISHU_APP_SECRET");
});

it("edits Skill content and MCP endpoint through the update UI; credentials stay outside the stored draft", async () => {
  const onDraftChange = vi.fn();
  await mount({ onDraftChange });
  await click("skillSourcePicker.edit");
  await input(
    document.querySelector('textarea[aria-label="skill file"]')!,
    "# edited skill",
  );
  await click("close file");
  const url = host.querySelector<HTMLInputElement>(
    'input[value="https://mcp.invalid/lookup"]',
  )!;
  expect(url).not.toBeNull();
  await input(url, "https://mcp.invalid/edited");
  await input(
    host.querySelector<HTMLInputElement>('input[type="password"]')!,
    "offline-synthetic-value",
  );
  await click("sourcePreserving.publish");
  const options = vi.mocked(deployAgentkitProject).mock.calls[0][3];
  expect(options?.draft?.selectedSkills?.[0].localFiles?.[0].content).toBe(
    "# edited skill",
  );
  expect(options?.draft?.mcpTools?.[0].url).toBe("https://mcp.invalid/edited");
  expect(generateAgentProject).not.toHaveBeenCalled();
  expect(onDraftChange).toHaveBeenCalled();
  expect(JSON.stringify(onDraftChange.mock.calls)).not.toContain(
    "offline-synthetic-value",
  );
  expect(JSON.stringify(options?.draft)).not.toContain(
    "offline-synthetic-value",
  );
  expect(options?.mcpSecretValues).toEqual([
    {
      agentName: "expert",
      name: "lookup",
      url: "https://mcp.invalid/edited",
      value: "offline-synthetic-value",
    },
  ]);
});

it("blocks incomplete release snapshots and invalid MCP endpoints before any publish request", async () => {
  await mount({ deploymentTarget: { ...target, etag: "" } });
  await click("sourcePreserving.publish");
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "sourcePreserving.reloadRequired",
  );
  expect(deployAgentkitProject).not.toHaveBeenCalled();
  await mount();
  await input(
    host.querySelector<HTMLInputElement>(
      'input[value="https://mcp.invalid/lookup"]',
    )!,
    "file:///tmp/no",
  );
  await click("sourcePreserving.publish");
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "sourcePreserving.invalidMcp",
  );
  expect(deployAgentkitProject).not.toHaveBeenCalled();
});

it("fences duplicate submissions and keeps an unconfirmed release from being submitted again", async () => {
  let reject!: (error: Error) => void;
  vi.mocked(deployAgentkitProject).mockReturnValue(
    new Promise((_resolve, fail) => {
      reject = fail;
    }),
  );
  const onDeploymentTaskChange = vi.fn();
  await mount({ onDeploymentTaskChange });
  await act(async () => {
    button("sourcePreserving.publish")!.click();
    button("sourcePreserving.publish")!.click();
  });
  expect(deployAgentkitProject).toHaveBeenCalledTimes(1);
  expect(host.querySelector("fieldset")?.disabled).toBe(true);
  await act(async () => reject(new DeploymentStatusUnconfirmedError()));
  await click("sourcePreserving.publish");
  expect(deployAgentkitProject).toHaveBeenCalledTimes(1);
  expect(onDeploymentTaskChange.mock.lastCall?.[0]).toMatchObject({
    status: "error",
    statusUnconfirmed: true,
  });
});

it("keeps ordinary agent creation on its existing workbench", async () => {
  await mount({ deploymentTarget: undefined });
  expect(button("sourcePreserving.publish")).toBeUndefined();
  expect(host.querySelector(".cw-build-workspace")).not.toBeNull();
});
