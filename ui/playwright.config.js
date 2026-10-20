import { defineConfig } from "@playwright/test";

// UI_PORT lets the tests run beside a console already serving on :8000.
const port = process.env.UI_PORT || "8000";

export default defineConfig({
  testDir: "tests",
  timeout: 60_000,
  workers: 4,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${port}` },
  webServer: {
    command: `cd ../agent && TIWALA_NO_WARM=1 TIWALA_AUTH_DISABLED=1 ../.venv/bin/uvicorn console.server:app --port ${port}`,
    url: `http://127.0.0.1:${port}/api/fixtures`,
    reuseExistingServer: true,
  },
});
