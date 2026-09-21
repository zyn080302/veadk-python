import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  test: {
    include: ["tests/sourcePreservingUpdate.test.tsx"],
    testTimeout: 20000,
  },
});
