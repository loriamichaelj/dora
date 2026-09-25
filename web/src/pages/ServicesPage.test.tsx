import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { bodyOf, json, page, service, SERVICE_ID, stubApi, summary } from '../test/fakeApi';
import { renderRoute } from '../test/render';

test('lists services and searches through the URL', async () => {
  const seen = stubApi({
    '/api/v1/services': (url) => json(page(url.searchParams.get('q') === 'zzz' ? [] : [service()])),
  });
  const { router } = renderRoute('/services');
  expect(await screen.findByRole('link', { name: 'Checkout API' })).toHaveAttribute(
    'href',
    `/services/${SERVICE_ID}`,
  );

  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Search by name or slug'), 'zzz');
  await user.click(screen.getByRole('button', { name: 'Search' }));
  expect(await screen.findByText('No services match “zzz”')).toBeInTheDocument();
  expect(router.state.location.search).toBe('?q=zzz');
  expect(seen.some((r) => new URL(r.url).searchParams.get('q') === 'zzz')).toBe(true);
});

test('create validates on the client before sending anything', async () => {
  const seen = stubApi({ '/api/v1/services': () => json(page([])) });
  renderRoute('/services');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'New service' }));
  await user.type(screen.getByLabelText('Slug'), 'Bad Slug');
  await user.click(screen.getByRole('button', { name: 'Create service' }));

  const slug = screen.getByLabelText('Slug');
  expect(slug).toHaveAttribute('aria-invalid', 'true');
  expect(slug).toHaveAccessibleDescription(/lowercase letters/);
  expect(screen.getByLabelText('Name')).toHaveAccessibleDescription(/Required/);
  expect(seen.filter((r) => r.method === 'POST')).toHaveLength(0);
});

test("the server's field errors appear inline (duplicate slug)", async () => {
  stubApi({
    '/api/v1/services': (_url, request) =>
      request.method === 'POST'
        ? new Response(
            JSON.stringify({
              type: 'urn:dora:problem:conflict',
              title: 'Conflict',
              status: 409,
              detail: "A service with slug 'checkout-api' already exists.",
              errors: [
                {
                  location: 'body',
                  field: 'slug',
                  message: 'This slug is already in use.',
                  type: 'unique',
                },
              ],
            }),
            { status: 409, headers: { 'content-type': 'application/problem+json' } },
          )
        : json(page([])),
  });
  renderRoute('/services');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'New service' }));
  await user.type(screen.getByLabelText('Slug'), 'checkout-api');
  await user.type(screen.getByLabelText('Name'), 'Checkout');
  await user.type(screen.getByLabelText('Owner team'), 'payments');
  await user.click(screen.getByRole('button', { name: 'Create service' }));

  await waitFor(() => {
    expect(screen.getByLabelText('Slug')).toHaveAccessibleDescription(
      /This slug is already in use/,
    );
  });
});

test('a successful create goes to the new service', async () => {
  let created: Record<string, unknown> | null = null;
  stubApi({
    '/api/v1/services': async (_url, request) => {
      if (request.method === 'POST') {
        created = await bodyOf(request);
        return json(service({ slug: 'new-api', name: 'New API' }), { status: 201 });
      }
      return json(page([]));
    },
    [`/api/v1/services/${SERVICE_ID}`]: () => json(service({ slug: 'new-api', name: 'New API' })),
    '/api/v1/metrics/dora': () => json(summary()),
    '/api/v1/deployments': () => json(page([])),
  });
  const { router } = renderRoute('/services');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'New service' }));
  await user.type(screen.getByLabelText('Slug'), 'new-api');
  await user.type(screen.getByLabelText('Name'), 'New API');
  await user.type(screen.getByLabelText('Owner team'), 'platform');
  await user.click(screen.getByRole('button', { name: 'Create service' }));

  await waitFor(() => {
    expect(router.state.location.pathname).toBe(`/services/${SERVICE_ID}`);
  });
  expect(created).toEqual({
    slug: 'new-api',
    name: 'New API',
    owner_team: 'platform',
    repo_url: null,
  });
});
