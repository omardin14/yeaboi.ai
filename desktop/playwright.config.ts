import { defineConfig } from "@playwright/test";

/**
 * Smoke test of the built frontend served by `vite preview`. This runs the web
 * UI in a real browser (no Tauri bridge), so it verifies the shell renders and
 * degrades gracefully without a backend. Run with `make e2e` (needs
 * `pnpm exec playwright install chromium` once).
 */
export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:4173" },
  webServer: {
    command: "pnpm preview --port 4173",
    url: "http://localhost:4173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
