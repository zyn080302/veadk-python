// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AgentWorkspace, type AgentWorkspaceProps } from "../src/ui/AgentWorkspace";
import { getRuntimeAgentInfo } from "../src/adk/client";
import type { AgentEntry } from "../src/adk/connections";

vi.mock("../src/adk/client", async (original) => ({
  ...(await original<object>()),
  getCachedRuntimeAgentInfo: () => null,
  getCachedRuntimeDetail: () => null,
  getCachedRuntimeUpdateCapability: () => null,
  prefetchRuntimeAgentInfo: vi.fn(),
  prefetchRuntimeDetail: vi.fn(),
  getRuntimeAgentInfo: vi.fn(),
  getRuntimeDetail: vi.fn(async () => ({ status: "Ready", networkTypes: [], envs: [] })),
  getRuntimeUpdateCapability: vi.fn(async ({ runtimeId, region }) => ({
    runtime: { runtimeId, region }, canUpdate: false, warnings: [],
  })),
}));
const { translation } = vi.hoisted(() => ({
  translation: { t: (key: string) => key, i18n: { language: "en-US" } },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => translation,
  initReactI18next: { type: "3rdParty", init() {} },
}));
vi.mock("../src/create/AgentBuildCanvas", () => ({ AgentBuildCanvas: () => null }));
vi.mock("../src/create/MarkdownPromptEditor", () => ({
  default: ({ value, onChange, readOnly }: { value: string; onChange: (value: string) => void; readOnly: boolean }) =>
    <textarea aria-label="additional instruction" value={value} readOnly={readOnly} onChange={e => onChange(e.target.value)} />,
}));

let root: ReturnType<typeof createRoot>;
let host: HTMLDivElement;
let requests: { url: string; method: string; body?: string }[];
let instruction: string;
let revision: number;
const first: AgentEntry = { id: "one", app: "expert", runtimeApp: "expert", label: "First", remote: true, runtimeId: "offline-one", region: "cn-shanghai" };
const second: AgentEntry = { ...first, id: "two", label: "Second", runtimeId: "offline-two" };
const info = { name: "expert", appName: "expert", description: "Offline expert", model: "offline", instructionExtension: true, tools: [], skills: [] };
async function mount(selected = first, overrides: Partial<AgentWorkspaceProps> = {}) {
  await act(async () => root.render(<AgentWorkspace
    agents={[first, second]} selectedAgentId={selected.id} focusedAgentId={selected.id}
    agentInfo={null} agentInfoAgentId="" loadingAgentInfo={false}
    detailOnly canCreate={false} canUpdate onSelectAgent={vi.fn()}
    onCreateAgent={vi.fn()} onUpdateAgent={vi.fn()} {...overrides}
  />));
}
function button(key: string) {
  return [...host.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent === key)!;
}
async function edit(value: string) {
  await act(async () => {
    const textarea = host.querySelector("textarea")!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
  Element.prototype.scrollIntoView = vi.fn();
  vi.mocked(getRuntimeAgentInfo).mockResolvedValue(info);
  requests = []; instruction = "original addition"; revision = 4;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    requests.push({ url: String(url), method: init.method || "GET", body: init.body as string | undefined });
    // The real client must address the chosen Runtime without any chat registration.
    if (!String(url).includes("/web/runtime-instruction/offline-") || !String(url).includes("/expert?")) {
      throw new Error("unexpected network boundary");
    }
    if (init.method === "PUT") {
      const value = JSON.parse(String(init.body));
      if (value.revision !== revision) return Response.json({}, { status: 409 });
      expect(Object.keys(value).sort()).toEqual(["instruction", "revision"]);
      instruction = value.instruction; revision++;
    }
    return Response.json({ instruction, revision, core_locked: true, core_position: "first", storage: "runtime_env", publication: init.method === "PUT" ? "pending" : "ready" });
  }));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

it("opens and saves in Runtime details without creating a conversation; stale revisions preserve edits", async () => {
  await mount();
  expect(host.querySelector("textarea")?.value).toBe("original addition");
  expect(requests).toHaveLength(1);
  await edit("customer addition");
  await act(async () => button("instructionExtension.saveAndPublish").click());
  expect(instruction).toBe("customer addition");
  expect(revision).toBe(5);
  expect(host.textContent).toContain("instructionExtension.publishPending");
  expect(button("instructionExtension.saveAndPublish").disabled).toBe(true);
  await act(async () => button("instructionExtension.reload").click());
  await edit("unsaved edit"); revision++;
  await act(async () => button("instructionExtension.saveAndPublish").click());
  expect(host.querySelector("textarea")?.value).toBe("unsaved edit");
  expect(host.textContent).toContain("instructionExtension.conflict");
  expect(button("instructionExtension.saveAndPublish").disabled).toBe(true);
  await act(async () => button("instructionExtension.reload").click());
  expect(host.querySelector("textarea")?.value).toBe("customer addition");
  expect(requests.every(r => r.url.includes("offline-one") && r.url.includes("region=cn-shanghai"))).toBe(true);
});

it("does not expose the editor without management permission or additive capability", async () => {
  await mount(first, { canUpdate: false });
  expect(host.querySelector("textarea")).toBeNull();
  expect(requests).toHaveLength(0);
  vi.mocked(getRuntimeAgentInfo).mockResolvedValue({ ...info, instructionExtension: false });
  await mount(second);
  expect(host.querySelector("textarea")).toBeNull();
  expect(requests).toHaveLength(0);
});

it("same app name on another Runtime cannot inherit the previous capability, text or revision", async () => {
  await mount();
  await edit("belongs to first Runtime");
  let resolveInfo!: (value: typeof info) => void;
  vi.mocked(getRuntimeAgentInfo).mockReturnValue(new Promise(resolve => { resolveInfo = resolve; }));
  await mount(second);
  expect(host.querySelector("textarea")).toBeNull();
  expect(requests).toHaveLength(1);
  instruction = "second Runtime"; revision = 9;
  await act(async () => resolveInfo(info));
  expect(host.querySelector("textarea")?.value).toBe("second Runtime");
  await edit("second addition");
  await act(async () => button("instructionExtension.saveAndPublish").click());
  expect(requests.at(-1)?.url).toContain("offline-two");
  expect(JSON.parse(requests.at(-1)!.body!)).toEqual({ instruction: "second addition", revision: 9 });
});
