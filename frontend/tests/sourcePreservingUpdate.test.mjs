import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
test("source-preserving update UI regression gate", { timeout: 90000 }, () => {
  const result = spawnSync(
    process.execPath,
    [
      "node_modules/vitest/vitest.mjs",
      "run",
      "-c",
      "vitest.source-preserving.config.ts",
    ],
    {
      cwd: fileURLToPath(new URL("..", import.meta.url)),
      encoding: "utf8",
      timeout: 85000,
    },
  );
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
