/** §12.4 scenarios 5, 6, and 8: the management UI end to end. */
import { expect, type Page, test } from '@playwright/test';

import { createService, ingest, minutesAgo, uniqueSlug } from './support';

async function dashboardCard(page: Page, serviceId: string, name: string) {
  await page.goto(`/?service=${serviceId}&window=7`);
  const card = page.getByRole('article', { name });
  await expect(card).toBeVisible();
  return card;
}

test('5 and 6. rollback + recorded failure moves change fail rate; resolving it gives a recovery time', async ({
  page,
  request,
}) => {
  const slug = uniqueSlug('e2e-rollback');
  const service = await createService(request, slug, 'E2E Rollback');
  const { body } = await ingest(request, {
    service_slug: slug,
    external_id: `gha-${slug}-1-production`,
    status: 'succeeded',
    started_at: minutesAgo(30),
    finished_at: minutesAgo(20),
  });

  // Before: one clean deployment.
  await expect(await dashboardCard(page, service.id, 'Change fail rate')).toContainText('0.0%');

  // 5. Mark it rolled back and record a failure through the prompt.
  await page.goto(`/deployments/${String(body.id)}`);
  await page.getByRole('button', { name: 'Mark rolled back' }).click();
  const prompt = page.getByRole('dialog', { name: 'Record a failure for this rollback?' });
  await prompt.getByLabel('Severity').selectOption('sev1');
  await prompt.getByLabel('Summary').fill('Checkout errors spiked');
  await prompt.getByRole('button', { name: 'Record failure' }).click();
  await expect(page.getByText('Failure recorded.')).toBeVisible();

  const cfr = await dashboardCard(page, service.id, 'Change fail rate');
  await expect(cfr).toContainText('100.0%');
  await expect(cfr).toContainText('Low');
  await expect(
    await dashboardCard(page, service.id, 'Failed deployment recovery time'),
  ).toContainText('1 open');

  // 6. Resolve it; the recovery card now shows a value.
  await page.goto(`/failures?service=${service.id}`);
  await page.getByRole('button', { name: 'Resolve: Checkout errors spiked' }).click();
  await page
    .getByRole('dialog', { name: 'Resolve failure' })
    .getByRole('button', { name: 'Resolve' })
    .click();
  await expect(page.getByText('Failure resolved.')).toBeVisible();

  const recovery = await dashboardCard(page, service.id, 'Failed deployment recovery time');
  await expect(recovery).toContainText('1 resolved failure · 0 open');
  await expect(recovery.getByText('—', { exact: true })).toHaveCount(0);
});

test('8. two browsers edit the same service; the second save gets the conflict message', async ({
  browser,
  request,
}) => {
  const service = await createService(request, uniqueSlug('e2e-conflict'), 'E2E Conflict');
  const [first, second] = await Promise.all([
    (await browser.newContext()).newPage(),
    (await browser.newContext()).newPage(),
  ]);
  for (const p of [first, second]) {
    await p.goto(`/services/${service.id}`);
    await expect(p.getByLabel('Name', { exact: true })).toHaveValue('E2E Conflict');
  }

  await first.getByLabel('Name', { exact: true }).fill('Saved first');
  await second.getByLabel('Name', { exact: true }).fill('Saved second');
  await first.getByRole('button', { name: 'Save changes' }).click();
  await expect(first.getByText('Saved.')).toBeVisible();

  await second.getByRole('button', { name: 'Save changes' }).click();
  await expect(
    second.getByText('This record was changed by someone else', { exact: false }),
  ).toBeVisible();
  // The second browser now shows what the first one saved.
  await expect(second.getByLabel('Name', { exact: true })).toHaveValue('Saved first');

  const stored = (await (await request.get(`/api/v1/services/${service.id}`)).json()) as {
    name: string;
    version: number;
  };
  expect(stored).toMatchObject({ name: 'Saved first', version: 2 });
});
