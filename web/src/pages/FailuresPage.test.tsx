import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { EDIT_CONFLICT_MESSAGE } from '../lib/useMutationErrors';
import { bodyOf, failure, json, page, service, stubApi } from '../test/fakeApi';
import { renderRoute } from '../test/render';

const FAILURE = failure();

test('defaults to open failures and filters through the URL', async () => {
  const seen = stubApi({
    '/api/v1/services': () => json(page([service()])),
    '/api/v1/failures': (url) =>
      json(
        page(
          url.searchParams.get('open') === 'false'
            ? [failure({ resolved_at: '2026-09-20T13:00:00Z' })]
            : [FAILURE],
        ),
      ),
  });
  const { router } = renderRoute('/failures');
  const table = await screen.findByRole('table');
  expect(within(table).getByRole('cell', { name: 'Open' })).toBeInTheDocument();
  const first = seen.find((r) => r.url.includes('/failures'));
  expect(new URL(first?.url ?? 'http://x').searchParams.get('open')).toBe('true');

  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText('Status'), 'Resolved');
  await waitFor(() => {
    expect(
      within(screen.getByRole('table')).getByRole('cell', { name: 'Resolved' }),
    ).toBeInTheDocument();
  });
  expect(router.state.location.search).toBe('?state=resolved');
  expect(screen.queryByRole('button', { name: /Resolve/ })).not.toBeInTheDocument();
});

test('Resolve sets resolved_at (editable, default now) with If-Match', async () => {
  const patches: Request[] = [];
  let items = [failure({ version: 3 })];
  stubApi({
    '/api/v1/services': () => json(page([service()])),
    '/api/v1/failures': () => json(page(items)),
    [`/api/v1/failures/${FAILURE.id}`]: (_url, request) => {
      patches.push(request);
      items = [];
      return json(failure({ resolved_at: '2026-09-20T13:00:00Z', version: 4 }));
    },
  });
  renderRoute('/failures');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: `Resolve: ${FAILURE.summary}` }));

  const dialog = await screen.findByRole('dialog', { name: 'Resolve failure' });
  const input = within(dialog).getByLabelText('Resolved at');
  expect(input).not.toHaveValue('');
  await user.clear(input);
  await user.type(input, '2026-09-20T06:00');
  await user.click(within(dialog).getByRole('button', { name: 'Resolve' }));

  await waitFor(() => {
    expect(patches).toHaveLength(1);
  });
  expect(patches[0]?.headers.get('if-match')).toBe('"3"');
  expect(await bodyOf(patches[0] as Request)).toEqual({
    resolved_at: new Date(2026, 8, 20, 6, 0).toISOString(),
  });
  expect(await screen.findByText('No open failures')).toBeInTheDocument();
});

test('a resolve that loses a race says so and reloads', async () => {
  let calls = 0;
  stubApi({
    '/api/v1/services': () => json(page([service()])),
    '/api/v1/failures': () => {
      calls += 1;
      return json(page([FAILURE]));
    },
    [`/api/v1/failures/${FAILURE.id}`]: () =>
      new Response(JSON.stringify({ type: 'x', title: 'Precondition Failed', status: 412 }), {
        status: 412,
        headers: { 'content-type': 'application/problem+json' },
      }),
  });
  renderRoute('/failures');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: `Resolve: ${FAILURE.summary}` }));
  const dialog = await screen.findByRole('dialog');
  await user.click(within(dialog).getByRole('button', { name: 'Resolve' }));

  expect(await screen.findByText(EDIT_CONFLICT_MESSAGE)).toBeInTheDocument();
  await waitFor(() => {
    expect(calls).toBeGreaterThan(1);
  });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('a server field error stays in the dialog, inline', async () => {
  stubApi({
    '/api/v1/services': () => json(page([service()])),
    '/api/v1/failures': () => json(page([FAILURE])),
    [`/api/v1/failures/${FAILURE.id}`]: () =>
      new Response(
        JSON.stringify({
          type: 'urn:dora:problem:validation',
          title: 'Unprocessable Content',
          status: 422,
          errors: [
            {
              location: 'body',
              field: 'resolved_at',
              message: 'Must be at or after detected_at.',
              type: 'before_detected',
            },
          ],
        }),
        { status: 422, headers: { 'content-type': 'application/problem+json' } },
      ),
  });
  renderRoute('/failures');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: `Resolve: ${FAILURE.summary}` }));
  const dialog = await screen.findByRole('dialog');
  await user.click(within(dialog).getByRole('button', { name: 'Resolve' }));
  await waitFor(() => {
    expect(within(dialog).getByLabelText('Resolved at')).toHaveAccessibleDescription(
      /at or after detected_at/,
    );
  });
});
