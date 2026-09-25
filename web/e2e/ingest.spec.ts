/** §12.4 scenarios 2, 3, and 4: the pipeline-facing ingest endpoint. */
import { expect, test } from '@playwright/test';

import { createService, ingest, minutesAgo, uniqueSlug } from './support';

test('2. a service created in the UI receives in_progress then succeeded as one deployment', async ({
  page,
  request,
}) => {
  const slug = uniqueSlug('e2e-ingest');
  await page.goto('/services');
  await page.getByRole('button', { name: 'New service' }).click();
  await page.getByLabel('Slug', { exact: true }).fill(slug);
  await page.getByLabel('Name', { exact: true }).fill('E2E Ingest');
  await page.getByLabel('Owner team').fill('e2e');
  await page.getByRole('button', { name: 'Create service' }).click();
  await expect(page.getByRole('heading', { name: 'E2E Ingest' })).toBeVisible();
  const serviceId = page.url().split('/services/')[1] ?? '';

  const externalId = `gha-${slug}-1-production`;
  const started = await ingest(request, {
    service_slug: slug,
    external_id: externalId,
    status: 'in_progress',
    started_at: minutesAgo(10),
  });
  expect(started.status).toBe(201);
  const finished = await ingest(request, {
    service_slug: slug,
    external_id: externalId,
    status: 'succeeded',
    started_at: minutesAgo(10),
    finished_at: minutesAgo(2),
  });
  expect(finished.status).toBe(200);
  expect(finished.body.id).toBe(started.body.id);

  await page.goto(`/deployments?service=${serviceId}`);
  const rows = page.getByRole('table').getByRole('row');
  await expect(rows).toHaveCount(2); // header + exactly one deployment
  await expect(rows.nth(1)).toContainText('Succeeded');
});

test('3. replaying the succeeded event changes nothing', async ({ request }) => {
  const slug = uniqueSlug('e2e-replay');
  await createService(request, slug);
  const event = {
    service_slug: slug,
    external_id: `gha-${slug}-1-production`,
    status: 'succeeded' as const,
    started_at: minutesAgo(10),
    finished_at: minutesAgo(2),
  };
  const first = await ingest(request, event);
  const replay = await ingest(request, event);
  expect(first.status).toBe(201);
  expect(replay.status).toBe(200);
  expect(replay.body).toEqual(first.body); // same id, same version, nothing touched

  const list = await request.get(`/api/v1/deployments?service_id=${String(first.body.service_id)}`);
  expect(((await list.json()) as { total: number }).total).toBe(1);
});

test('4. a late in_progress after succeeded is ignored as stale', async ({ request }) => {
  const slug = uniqueSlug('e2e-stale');
  await createService(request, slug);
  const externalId = `gha-${slug}-1-production`;
  const done = await ingest(request, {
    service_slug: slug,
    external_id: externalId,
    status: 'succeeded',
    started_at: minutesAgo(10),
    finished_at: minutesAgo(2),
  });
  const late = await ingest(request, {
    service_slug: slug,
    external_id: externalId,
    status: 'in_progress',
    started_at: minutesAgo(10),
  });
  expect(late.status).toBe(200);
  expect(late.body.ignored).toBe('stale_event');
  expect(late.body.status).toBe('succeeded');
  expect(late.body.version).toBe(done.body.version);
});
