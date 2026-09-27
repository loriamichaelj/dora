/**
 * Browser smoke test for a deployed environment (cloud design §7.2 step 10).
 *
 *   SMOKE_BASE_URL=http://<alb-dns-name> npx playwright test -c playwright.smoke.config.ts
 *
 * Read-only: it creates no data, so it can run against any environment. Each
 * page must render with no uncaught page error, no console error, no API
 * response >= 400, and no error state. That catches browser-only failures the
 * curl checks (scripts/deploy/smoke_test.py) can't. `make e2e` also runs it
 * against the local stack.
 */
import { expect, type Page, test } from '@playwright/test';

function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console error: ${msg.text()}`);
  });
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) {
      const path = new URL(res.url()).pathname;
      problems.push(`API ${String(res.status())} ${res.request().method()} ${path}`);
    }
  });
  return problems;
}

/** The page has its heading, has finished loading, and isn't in its error state. */
async function settled(page: Page, heading?: string): Promise<void> {
  await expect(
    page.getByRole('heading', { level: 1, ...(heading ? { name: heading } : {}) }),
  ).toBeVisible();
  await expect(page.getByRole('status')).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
}

const PAGES = [
  ['/', 'DORA Metrics'],
  ['/services', 'Services'],
  ['/deployments', 'Deployments'],
  ['/failures', 'Failures'],
  ['/deployments/new', 'New deployment'],
] as const;

for (const [path, heading] of PAGES) {
  test(`${path} renders without errors`, async ({ page }) => {
    const problems = watch(page);
    await page.goto(path);
    await settled(page, heading);
    expect(problems).toEqual([]);
  });
}

// A fresh environment has no rows yet; then there's nothing to open.
for (const [path, heading] of [
  ['/services', 'Services'],
  ['/deployments', 'Deployments'],
] as const) {
  test(`the first row of ${path} opens its detail page`, async ({ page }) => {
    const problems = watch(page);
    await page.goto(path);
    await settled(page, heading);
    const link = page.getByRole('table').getByRole('link').first();
    if ((await link.count()) === 0) {
      test.info().annotations.push({ type: 'note', description: `${path} has no rows yet` });
      return;
    }
    await link.click();
    await settled(page);
    expect(problems).toEqual([]);
  });
}
