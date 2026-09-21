import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const require = createRequire(import.meta.url);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
};
const snapshot = (instruction, revision = 0) => ({ instruction, revision, core_locked: true, core_position: "first" });

async function mount() {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost" });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  for (const name of ["SVGElement", "HTMLElement", "Element", "Node", "Event", "MouseEvent"]) globalThis[name] = dom.window[name];
  globalThis.requestAnimationFrame = callback => setTimeout(callback, 0);
  globalThis.cancelAnimationFrame = clearTimeout;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require("react");
  const { act } = React;
  const requests = [];
  class RequestError extends Error { constructor(status) { super(); this.status = status; } }
  globalThis.instructionApi = {
    InstructionExtensionError: RequestError,
    instructionExtension: (app, edit, signal) => {
      const item = { ...deferred(), app, edit, signal };
      requests.push(item);
      return item.promise;
    },
  };
  const result = await build({
    entryPoints: [fileURLToPath(new URL("../src/ui/InstructionExtensionEditor.tsx", import.meta.url))],
    bundle: true, platform: "node", format: "cjs", write: false,
    external: ["react", "react/jsx-runtime"], loader: { ".css": "empty" },
    plugins: [{ name: "boundaries", setup(b) {
      b.onResolve({ filter: /^react-i18next$/ }, () => ({ path: "i18n", namespace: "mock" }));
      b.onLoad({ filter: /.*/, namespace: "mock" }, () => ({ contents: 'export const useTranslation=()=>({t:k=>k});' }));
      b.onLoad({ filter: /adk\/client\.ts$/ }, () => ({ contents: 'export const {instructionExtension,InstructionExtensionError}=globalThis.instructionApi;' }));
      // Exercise the editor container's real events without depending on Lexical's DOM APIs.
      b.onLoad({ filter: /MarkdownPromptEditor\.tsx$/ }, () => ({ contents: 'import React from "react"; export default function Editor({value,onChange,readOnly}) {return React.createElement("textarea",{value,readOnly,onChange:e=>onChange(e.target.value)});}' }));
    } }],
  });
  const module = { exports: {} };
  Function("require", "module", "exports", result.outputFiles[0].text)(require, module, module.exports);
  const root = require("react-dom/client").createRoot(document.getElementById("root"));
  const render = appName => act(async () => root.render(React.createElement(module.exports.InstructionExtensionEditor, { key: appName, appName })));
  const button = suffix => [...document.querySelectorAll("button")].find(b => b.textContent === `instructionExtension.${suffix}`);
  const input = async value => act(async () => {
    const el = document.querySelector("textarea");
    Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  });
  return { dom, act, requests, render, button, input, RequestError,
    close: async () => { await act(async () => root.unmount()); dom.window.close(); },
  };
}

test("edit, save and reload preserve the additional layer; duplicate and IME submissions are fenced", async () => {
  const v = await mount();
  try {
    await v.render("expert");
    assert.equal(v.button("save").disabled, true);
    await v.act(async () => v.requests[0].resolve(snapshot("initial")));
    await v.input("客户新增说明");
    assert.equal(v.button("save").disabled, false);
    await v.act(async () => document.querySelector("textarea").dispatchEvent(new v.dom.window.CompositionEvent("compositionstart", { bubbles: true })));
    await v.act(async () => v.button("save").click());
    assert.equal(v.requests.length, 1);
    await v.act(async () => document.querySelector("textarea").dispatchEvent(new v.dom.window.KeyboardEvent("keydown", { key: "Enter", keyCode: 229, isComposing: true, bubbles: true })));
    assert.equal(v.requests.length, 1);
    await v.act(async () => document.querySelector("textarea").dispatchEvent(new v.dom.window.CompositionEvent("compositionend", { bubbles: true })));
    await v.act(async () => { v.button("save").click(); v.button("save").click(); });
    assert.equal(v.requests.length, 2);
    assert.deepEqual(v.requests[1].edit, { instruction: "客户新增说明", revision: 0 });
    assert.equal(document.querySelector("textarea").readOnly, true);
    await v.act(async () => v.requests[1].resolve(snapshot("客户新增说明", 1)));
    assert.match(document.querySelector('[role="status"]').textContent, /saved/);
    await v.act(async () => v.button("reload").click());
    await v.act(async () => v.requests[2].resolve(snapshot("客户新增说明", 1)));
    assert.equal(document.querySelector("textarea").value, "客户新增说明");
    await v.input("");
    await v.act(async () => v.button("save").click());
    assert.deepEqual(v.requests[3].edit, { instruction: "", revision: 1 });
  } finally { await v.close(); }
});

test("load errors are retryable and stale responses cannot affect a different Agent", async () => {
  const v = await mount();
  try {
    await v.render("one");
    await v.act(async () => v.requests[0].reject(new Error("offline")));
    assert.match(document.querySelector('[role="alert"]').textContent, /loadError/);
    await v.act(async () => v.button("reload").click());
    await v.render("two");
    assert.equal(v.requests[1].signal.aborted, true);
    await v.act(async () => v.requests[2].resolve(snapshot("second")));
    await v.act(async () => v.requests[1].resolve(snapshot("wrong agent")));
    assert.equal(document.querySelector("textarea").value, "second");
  } finally { await v.close(); }
});

test("conflicts preserve unsaved text and block accidental overwrite until reload", async () => {
  const v = await mount();
  try {
    await v.render("expert");
    await v.act(async () => v.requests[0].resolve(snapshot("initial")));
    await v.input("unsaved");
    await v.act(async () => v.button("save").click());
    await v.act(async () => v.requests[1].reject(new v.RequestError(409)));
    assert.equal(document.querySelector("textarea").value, "unsaved");
    assert.match(document.querySelector('[role="alert"]').textContent, /conflict/);
    assert.equal(v.button("save").disabled, true);
    await v.act(async () => v.button("reload").click());
    await v.act(async () => v.requests[2].resolve(snapshot("other edit", 2)));
    await v.input("merged");
    await v.act(async () => v.button("save").click());
    assert.deepEqual(v.requests[3].edit, { instruction: "merged", revision: 2 });
    await v.act(async () => v.requests[3].reject(new v.RequestError(503)));
    assert.match(document.querySelector('[role="alert"]').textContent, /saveError/);
    assert.equal(v.button("save").disabled, false);
    await v.input("x".repeat(65537));
    assert.equal(v.button("save").disabled, true);
  } finally { await v.close(); }
});


test("cloud edits submit a publication and remain locked until a ready reload", async () => {
  const v = await mount();
  const cloud = (text, revision, publication) => ({...snapshot(text, revision), storage: "runtime_env", publication});
  try {
    await v.render("expert");
    await v.act(async () => v.requests[0].resolve(cloud("initial", 4, "ready")));
    assert.equal(v.button("saveAndPublish").disabled, true);
    await v.input("新增说明");
    await v.act(async () => v.button("saveAndPublish").click());
    assert.deepEqual(v.requests[1].edit, {instruction: "新增说明", revision: 4});
    await v.act(async () => v.requests[1].resolve(cloud("新增说明", 4, "pending")));
    assert.equal(v.button("saveAndPublish").disabled, true);
    assert.equal(document.querySelector("textarea").readOnly, true);
    assert.equal(document.querySelector('[role="status"]').textContent, "instructionExtension.publishPending");
    await v.act(async () => v.button("reload").click());
    await v.act(async () => v.requests[2].resolve(cloud("新增说明", 5, "ready")));
    assert.equal(document.querySelector("textarea").readOnly, false);
    await v.input("");
    await v.act(async () => v.button("saveAndPublish").click());
    assert.deepEqual(v.requests[3].edit, {instruction: "", revision: 5});
    await v.act(async () => v.requests[3].reject(new v.RequestError(502)));
    assert.equal(v.button("saveAndPublish").disabled, true);
    assert.equal(document.querySelector('[role="alert"]').textContent, "instructionExtension.publishError");
    await v.act(async () => v.button("reload").click());
    await v.act(async () => v.requests[4].resolve(cloud("", 5, "unknown")));
    assert.equal(document.querySelector('[role="status"]').textContent, "instructionExtension.publishUnknown");
  } finally { await v.close(); }
});
