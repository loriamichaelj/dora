/** §12.4 scenarios 1 (cold start) and 7 (liveness vs readiness). */
import { expect, test } from '@playwright/test';

import { compose, containerState } from './support';

test('1. cold start: dashboard loads; healthz, readyz, and version answer', async ({
  page,
  request,
}) => {
  // `make e2e` starts this project from an empty volume (down -v, then up).
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'DORA metrics' })).toBeVisible();
  await expect(page.getByRole('article', { name: 'Deployment frequency' })).toBeVisible();

  expect((await request.get('/healthz')).status()).toBe(200);
  const ready = await request.get('/readyz');
  expect(ready.status()).toBe(200);
  expect(await ready.json()).toEqual({ status: 'ready', checks: { database: 'ok' } });

  const version = (await (await request.get('/version')).json()) as Record<string, string>;
  expect(Object.keys(version).sort()).toEqual(['build_time', 'git_sha', 'version']);
  // The Makefile passes the checked-out commit into the image build.
  if (process.env.GIT_SHA) expect(version.git_sha).toBe(process.env.GIT_SHA);

  // /metrics is the API's alone; through nginx it's the SPA, never Prometheus.
  const metrics = await request.get('/metrics');
  expect(await metrics.text()).not.toContain('http_requests_total');
});

test('7. a database outage fails readiness, not liveness, and heals without an api restart', async ({
  page,
  request,
}) => {
  const before = containerState('api');
  compose('stop', 'db');
  try {
    await expect.poll(async () => (await request.get('/readyz')).status()).toBe(503);
    expect((await request.get('/healthz')).status()).toBe(200);

    await page.goto('/');
    const alert = page.getByRole('alert');
    await expect(alert).toContainText('The database is unavailable', { timeout: 20_000 });
    await expect(alert).toContainText('Request ID');

    // Let the container healthcheck run several times while the DB is down.
    await page.waitForTimeout(25_000);
    expect(containerState('api')).toEqual({ startedAt: before.startedAt, health: 'healthy' });
  } finally {
    compose('start', 'db');
  }

  await expect
    .poll(async () => (await request.get('/readyz')).status(), { timeout: 60_000 })
    .toBe(200);
  expect(containerState('api').startedAt).toBe(before.startedAt); // never restarted

  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('article', { name: 'Deployment frequency' })).toBeVisible();
});
