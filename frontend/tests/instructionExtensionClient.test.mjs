import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "vite";
import { JSDOM } from "jsdom";

test("instruction client uses Runtime control-plane publication and preserves local saves", async t => {
  const dom = new JSDOM("", { url: "http://localhost" });
  globalThis.window = dom.window;
  globalThis.localStorage = dom.window.localStorage;
  globalThis.sessionStorage = dom.window.sessionStorage;
  t.after(() => dom.window.close());
  const server = await createServer({ logLevel: "silent", server: { middlewareMode: true }, appType: "custom", cacheDir: ".cache/aiops-vite" });
  t.after(() => server.close());
  const client = await server.ssrLoadModule("/src/adk/client.ts");
  client.registerRemoteApp("display-id", { app: "expert", runtimeId: "offline-runtime", region: "cn-beijing" });
  const calls = [];
  let response = { instruction: "addition", revision: 1, core_locked: true, core_position: "first", storage: "runtime_env", publication: "ready" };
  let status = 200;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, init });
    return Response.json(response, { status });
  });
  const edit = { instruction: "addition", revision: 0, core_instruction: "must never be serialized" };
  await client.instructionExtension("display-id", edit);
  assert.match(calls[0].url, /\/web\/runtime-instruction\/offline-runtime\/expert/);
  assert.equal(calls[0].init.method, "PUT");
  assert.deepEqual(JSON.parse(calls[0].init.body), { instruction: "addition", revision: 0 });
  await client.instructionExtension("display-id");
  assert.equal(calls[1].init.method, "GET");
  assert.equal(calls[1].init.body, undefined);
  // Detail pages have no registered chat connection. The explicit Runtime wins
  // even when another chat connection happens to use the same display name.
  const target = { runtimeId: "detail-runtime", region: "cn-shanghai" };
  await client.instructionExtension("display-id", edit, undefined, target);
  assert.match(calls[2].url, /\/web\/runtime-instruction\/detail-runtime\/display-id/);
  assert.match(calls[2].url, /region=cn-shanghai/);
  assert.deepEqual(JSON.parse(calls[2].init.body), { instruction: "addition", revision: 0 });
  const callCount = calls.length;
  await assert.rejects(client.instructionExtension("expert", undefined, undefined, { runtimeId: "", region: "cn-shanghai" }));
  await assert.rejects(client.instructionExtension("expert", undefined, undefined, { runtimeId: "detail-runtime", region: "" }));
  assert.equal(calls.length, callCount, "invalid targets must not fall back to the local agent");
  await client.instructionExtension("local-agent", edit);
  assert.match(calls.at(-1).url, /\/web\/aiops-extension\/local-agent/);
  assert.equal(calls.at(-1).init.method, "PUT");
  status = 409;
  await assert.rejects(client.instructionExtension("display-id", edit), error => error.status === 409);
  status = 200;
  response = { ...response, core_locked: false };
  await assert.rejects(client.instructionExtension("display-id"), error => error.status === 502);
  response = { ...response, core_locked: true, revision: -1 };
  await assert.rejects(client.instructionExtension("display-id"), error => error.status === 502);
});
