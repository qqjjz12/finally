import { defineConfig } from '@playwright/test';

const port = process.env.E2E_PORT || '8765';
const baseURL = process.env.BASE_URL || `http://localhost:${port}`;

export default defineConfig({
  testDir: './tests',
  workers: 1, // tests share one app instance / DB
  fullyParallel: false,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  use: { baseURL, trace: 'retain-on-failure' },
  // Locally (no BASE_URL) start backend with a fresh DB; in docker the app is a separate service.
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: 'node start-server.mjs',
        url: `http://localhost:${port}/api/health`,
        reuseExistingServer: false,
        timeout: 120_000,
      },
});
