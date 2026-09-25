import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { EDIT_CONFLICT_MESSAGE } from '../lib/useMutationErrors';
import {
  bodyOf,
  deployment,
  json,
  page,
  service,
  SERVICE_ID,
  stubApi,
  summary,
} from '../test/fakeApi';
import { renderRoute } from '../test/render';

const URL_PATH = `/api/v1/services/${SERVICE_ID}`;

function baseRoutes() {
  return {
    '/api/v1/metrics/dora': () => json(summary()),
    '/api/v1/deployments': () => json(page([deployment()])),
  };
}

test('shows details, metrics, and recent deployments', async () => {
  stubApi({ ...baseRoutes(), [URL_PATH]: () => json(service()) });
  renderRoute(`/services/${SERVICE_ID}`);
  expect(await screen.findByRole('heading', { name: 'Checkout API' })).toBeInTheDocument();
  expect(screen.getByLabelText('Slug')).toHaveAttribute('readonly');
  expect(await screen.findByRole('article', { name: 'Change fail rate' })).toHaveTextContent('Low');
  const recent = screen.getByRole('region', { name: 'Recent deployments' });
  expect(await within(recent).findByText('v1.4.2')).toBeInTheDocument();
});

test('saving sends If-Match with the loaded version', async () => {
  const patches: Request[] = [];
  stubApi({
    ...baseRoutes(),
    [URL_PATH]: async (_url, request) => {
      if (request.method === 'PATCH') {
        patches.push(request);
        const body = await bodyOf(request);
        return json(service({ ...body, version: 4 }), { headers: { etag: '"4"' } });
      }
      return json(service({ version: 3 }));
    },
  });
  renderRoute(`/services/${SERVICE_ID}`);
  const user = userEvent.setup();
  const name = await screen.findByLabelText('Name');
  await user.clear(name);
  await user.type(name, 'Checkout Service');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));

  await waitFor(() => {
    expect(patches).toHaveLength(1);
  });
  expect(patches[0]?.headers.get('if-match')).toBe('"3"');
  expect(await bodyOf(patches[0] as Request)).toEqual({
    name: 'Checkout Service',
    owner_team: 'payments',
    repo_url: null,
  });
  expect(await screen.findByText('Saved.')).toBeInTheDocument();
});

test('a 412 says someone else changed it and loads their version', async () => {
  let current = service({ version: 1 });
  stubApi({
    ...baseRoutes(),
    [URL_PATH]: (_url, request) => {
      if (request.method === 'PATCH') {
        // Someone else saved first.
        current = service({ version: 2, name: 'Renamed Elsewhere' });
        return new Response(
          JSON.stringify({ type: 'x', title: 'Precondition Failed', status: 412 }),
          {
            status: 412,
            headers: { 'content-type': 'application/problem+json', 'x-request-id': 'req-412' },
          },
        );
      }
      return json(current);
    },
  });
  renderRoute(`/services/${SERVICE_ID}`);
  const user = userEvent.setup();
  const name = await screen.findByLabelText('Name');
  await user.clear(name);
  await user.type(name, 'My Edit');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));

  expect(await screen.findByText(EDIT_CONFLICT_MESSAGE)).toBeInTheDocument();
  expect(screen.getByText('req-412')).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByLabelText('Name')).toHaveValue('Renamed Elsewhere');
  });
  expect(screen.getByText('Version 2')).toBeInTheDocument();
});
