import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { bodyOf, deployment, DEPLOYMENT_ID, json, page, service, stubApi } from '../test/fakeApi';
import { renderRoute } from '../test/render';

test('finished_at is required for a finished deployment and forbidden in progress', async () => {
  const seen = stubApi({ '/api/v1/services': () => json(page([service()])) });
  renderRoute('/deployments/new');
  const user = userEvent.setup();
  await screen.findByRole('option', { name: 'Checkout API' });
  await user.selectOptions(screen.getByLabelText('Service'), 'Checkout API');
  await user.type(screen.getByLabelText('Release'), 'v2');
  await user.clear(screen.getByLabelText('Finished at'));
  await user.click(screen.getByRole('button', { name: 'Record deployment' }));
  expect(screen.getByLabelText('Finished at')).toHaveAccessibleDescription(
    /Required for this status/,
  );

  await user.selectOptions(screen.getByLabelText('Status'), 'In progress');
  await user.type(screen.getByLabelText('Finished at'), '2026-09-20T10:00');
  await user.click(screen.getByRole('button', { name: 'Record deployment' }));
  expect(screen.getByLabelText('Finished at')).toHaveAccessibleDescription(/Leave empty/);
  expect(seen.filter((r) => r.method === 'POST')).toHaveLength(0);
});

test('posts offset-aware timestamps and opens the new deployment', async () => {
  let posted: Record<string, unknown> | null = null;
  stubApi({
    '/api/v1/services': () => json(page([service()])),
    '/api/v1/deployments': async (_url, request) => {
      posted = await bodyOf(request);
      return json(deployment(), { status: 201 });
    },
    [`/api/v1/deployments/${DEPLOYMENT_ID}`]: () => json(deployment()),
    [`/api/v1/services/${service().id}`]: () => json(service()),
  });
  const { router } = renderRoute('/deployments/new');
  const user = userEvent.setup();
  await screen.findByRole('option', { name: 'Checkout API' });
  await user.selectOptions(screen.getByLabelText('Service'), 'Checkout API');
  await user.type(screen.getByLabelText('Release'), 'v2.0.0');
  await user.click(screen.getByRole('button', { name: 'Record deployment' }));

  await waitFor(() => {
    expect(router.state.location.pathname).toBe(`/deployments/${DEPLOYMENT_ID}`);
  });
  expect(posted).toMatchObject({
    service_id: service().id,
    environment: 'production',
    kind: 'planned',
    release: 'v2.0.0',
    status: 'succeeded',
    head_sha: null,
  });
  const body = posted as unknown as { started_at: string; finished_at: string };
  expect(body.started_at).toMatch(/Z$/);
  expect(body.finished_at).toMatch(/Z$/);
});
