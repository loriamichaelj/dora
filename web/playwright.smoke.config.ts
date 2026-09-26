/**
 * Browser smoke test of a running environment (e2e/deployed.smoke.ts). Used by
 * deploy.yml after every rollout, and by `make e2e` against the local stack.
 * The regular E2E config never picks these files up: they aren't *.spec.ts.
 */
import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.SMOKE_BASE_URL;
if (!baseURL) {
  throw new Error('Set SMOKE_BASE_URL to the environment to test, e.g. http://<alb-dns-name>');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.smoke.ts',
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: '../reports/playwright/smoke-results',
  use: { baseURL, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
