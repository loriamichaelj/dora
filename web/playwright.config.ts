/**
 * E2E against the isolated Compose project (§12.4). Run it with `make e2e`,
 * which builds and seeds the `dora-e2e` stack, runs these tests, and tears
 * the stack down again.
 */
import { defineConfig, devices } from '@playwright/test';

const reports = '../reports';

export default defineConfig({
  testDir: './e2e',
  // One worker, in order: scenario 7 stops the database, and every scenario
  // shares one stack.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['junit', { outputFile: `${reports}/junit-e2e.xml` }],
    ['html', { outputFolder: `${reports}/playwright/html`, open: 'never' }],
  ],
  outputDir: `${reports}/playwright/results`,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:18080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
