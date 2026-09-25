/** §12.4 scenario 9: the seeded profiles show through the dashboard. */
import { expect, type Page, test } from '@playwright/test';

async function serviceIds(page: Page): Promise<Map<string, string>> {
  const resp = await page.request.get('/api/v1/services?limit=200');
  const { items } = (await resp.json()) as { items: { id: string; slug: string }[] };
  return new Map(items.map((s) => [s.slug, s.id]));
}

test('9. seeded bands over the seed window: checkout elite, legacy low, new-svc empty', async ({
  page,
}) => {
  const ids = await serviceIds(page);
  // Read over the seed's 90-day window (D57).
  await page.goto(`/?service=${ids.get('checkout-api') ?? ''}&window=90`);
  await expect(page.getByRole('article', { name: 'Deployment frequency' })).toContainText('Elite');

  await page.goto(`/?service=${ids.get('legacy-billing') ?? ''}&window=90`);
  await expect(page.getByRole('article', { name: 'Change fail rate' })).toContainText('Low');

  await page.goto(`/?service=${ids.get('new-svc') ?? ''}&window=90`);
  await expect(page.getByText('No deployments in this window')).toBeVisible();
  await expect(page.getByRole('article')).toHaveCount(0);
});
