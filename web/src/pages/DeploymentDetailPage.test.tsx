import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Schemas } from '../api/client';
import {
  bodyOf,
  deployment,
  DEPLOYMENT_ID,
  failure,
  json,
  service,
  SERVICE_ID,
  stubApi,
} from '../test/fakeApi';
import { renderRoute } from '../test/render';

const PATH = `/api/v1/deployments/${DEPLOYMENT_ID}`;

function routes(current: () => Schemas['DeploymentDetail']) {
  return {
    [`/api/v1/services/${SERVICE_ID}`]: () => json(service()),
    [PATH]: () => json(current()),
  };
}

test.each([
  ['in_progress', ['Mark succeeded', 'Mark failed'], false],
  ['succeeded', ['Mark rolled back'], true],
  ['failed', [], false],
  ['rolled_back', [], true],
] as const)('%s offers only its valid transitions', async (status, actions, canRecord) => {
  const d = deployment({
    status,
    finished_at: status === 'in_progress' ? null : '2026-09-20T10:07:30Z',
  });
  stubApi(routes(() => d));
  renderRoute(`/deployments/${DEPLOYMENT_ID}`);
  await screen.findByRole('heading', { name: 'v1.4.2' });

  const all = ['Mark succeeded', 'Mark failed', 'Mark rolled back'];
  for (const label of all) {
    const button = screen.queryByRole('button', { name: label });
    if ((actions as readonly string[]).includes(label)) expect(button).toBeInTheDocument();
    else expect(button).not.toBeInTheDocument();
  }
  expect(Boolean(screen.queryByRole('button', { name: 'Record failure' }))).toBe(canRecord);
});

test('completing an in-progress deployment sends finished_at and If-Match', async () => {
  let current = deployment({ status: 'in_progress', finished_at: null, version: 5 });
  const patches: Record<string, unknown>[] = [];
  stubApi({
    ...routes(() => current),
    [PATH]: async (_url, request) => {
      if (request.method === 'PATCH') {
        expect(request.headers.get('if-match')).toBe('"5"');
        const body = await bodyOf(request);
        patches.push(body);
        current = deployment({ status: 'succeeded', version: 6 });
        return json(current);
      }
      return json(current);
    },
  });
  renderRoute(`/deployments/${DEPLOYMENT_ID}`);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Mark succeeded' }));
  await waitFor(() => {
    expect(patches).toHaveLength(1);
  });
  expect(patches[0]?.status).toBe('succeeded');
  expect(typeof patches[0]?.finished_at).toBe('string');
  expect(await screen.findByRole('button', { name: 'Mark rolled back' })).toBeInTheDocument();
});

test('marking rolled back asks whether to record a failure, and records it', async () => {
  let current = deployment({ status: 'succeeded', version: 1 });
  const posted: Record<string, unknown>[] = [];
  stubApi({
    ...routes(() => current),
    [PATH]: (_url, request) => {
      if (request.method === 'PATCH') current = deployment({ status: 'rolled_back', version: 2 });
      return json(current);
    },
    '/api/v1/failures': async (_url, request) => {
      posted.push(await bodyOf(request));
      current = deployment({ status: 'rolled_back', version: 2, failures: [failure()] });
      return json(failure(), { status: 201 });
    },
  });
  renderRoute(`/deployments/${DEPLOYMENT_ID}`);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Mark rolled back' }));

  const dialog = await screen.findByRole('dialog', {
    name: 'Record a failure for this rollback?',
  });
  expect(dialog).toHaveTextContent('doesn’t count as a failure on its own');
  await user.selectOptions(within(dialog).getByLabelText('Severity'), 'SEV1');
  await user.type(within(dialog).getByLabelText('Summary'), 'Checkout errors spiked');
  await user.click(within(dialog).getByRole('button', { name: 'Record failure' }));

  await waitFor(() => {
    expect(posted).toHaveLength(1);
  });
  expect(posted[0]).toMatchObject({
    deployment_id: DEPLOYMENT_ID,
    severity: 'sev1',
    summary: 'Checkout errors spiked',
    resolved_at: null,
  });
  expect(typeof posted[0]?.detected_at).toBe('string');
  expect(await screen.findByText('Failure recorded.')).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('"Not now" closes the prompt without recording anything', async () => {
  let current = deployment({ status: 'succeeded' });
  const seen = stubApi({
    ...routes(() => current),
    [PATH]: (_url, request) => {
      if (request.method === 'PATCH') current = deployment({ status: 'rolled_back', version: 2 });
      return json(current);
    },
  });
  renderRoute(`/deployments/${DEPLOYMENT_ID}`);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Mark rolled back' }));
  const dialog = await screen.findByRole('dialog');
  await user.click(within(dialog).getByRole('button', { name: 'Not now' }));
  await waitFor(() => {
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  expect(seen.some((r) => r.url.includes('/failures'))).toBe(false);
});

test('shows commits and failures', async () => {
  stubApi(
    routes(() => deployment({ failures: [{ ...failure(), resolved_at: '2026-09-20T13:00:00Z' }] })),
  );
  renderRoute(`/deployments/${DEPLOYMENT_ID}`);
  const commits = await screen.findByRole('region', { name: 'Commits (1)' });
  expect(within(commits).getByText('9f2c1ab')).toBeInTheDocument();
  expect(within(commits).getByText('fix: retry on 503')).toBeInTheDocument();
  const failures = screen.getByRole('region', { name: 'Failures' });
  expect(within(failures).getByText('Resolved')).toBeInTheDocument();
});
