import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  timeout: 60_000,
  workers: 4,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8000" },
  webServer: {
    command: "cd ../agent && TIWALA_NO_WARM=1 TIWALA_AUTH_DISABLED=1 ../.venv/bin/uvicorn console.server:app --port 8000",
    url: "http://127.0.0.1:8000/api/fixtures",
    reuseExistingServer: true,
  },
});
