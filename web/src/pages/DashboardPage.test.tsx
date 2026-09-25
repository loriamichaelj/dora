import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  EMPTY_SUMMARY,
  json,
  problem,
  SERVICES,
  stubApi,
  summary,
  TIMESERIES,
} from '../test/fakeApi';
import { renderRoute } from '../test/render';
import { DISCLAIMER } from './DashboardPage';

function card(name: string): HTMLElement {
  return screen.getByRole('article', { name });
}

test('renders the five metrics with bands, grouped, plus trends and disclaimer', async () => {
  stubApi({
    '/api/v1/services': () => json(SERVICES),
    '/api/v1/metrics/dora': () => json(summary()),
    '/api/v1/metrics/dora/timeseries': () => json(TIMESERIES),
  });
  renderRoute('/');

  await screen.findByRole('article', { name: 'Deployment frequency' });
  const throughput = screen.getByRole('region', { name: 'Throughput' });
  const instability = screen.getByRole('region', { name: 'Instability' });
  expect(within(throughput).getAllByRole('article')).toHaveLength(3);
  expect(within(instability).getAllByRole('article')).toHaveLength(2);

  expect(card('Deployment frequency')).toHaveTextContent('4.0 / month');
  expect(card('Deployment frequency')).toHaveTextContent('Medium');
  expect(card('Change lead time')).toHaveTextContent('19.0 h');
  expect(card('Change lead time')).toHaveTextContent('Elite');
  expect(card('Change fail rate')).toHaveTextContent('50.0%');
  expect(card('Change fail rate')).toHaveTextContent('Low');
  expect(card('Failed deployment recovery time')).toHaveTextContent('High');
  expect(card('Failed deployment recovery time')).toHaveTextContent('1 open');
  expect(card('Deployment rework rate')).toHaveTextContent('No published benchmark');

  expect(await screen.findByRole('table', { name: 'Deployments per week' })).toBeInTheDocument();
  expect(screen.getByText(DISCLAIMER, { exact: false })).toBeInTheDocument();
});

test('an empty window shows the empty state, not zeros', async () => {
  stubApi({
    '/api/v1/services': () => json(SERVICES),
    '/api/v1/metrics/dora': () => json(EMPTY_SUMMARY),
    '/api/v1/metrics/dora/timeseries': () => json(TIMESERIES),
  });
  renderRoute('/');
  expect(await screen.findByText('No deployments in this window')).toBeInTheDocument();
  expect(screen.queryByRole('article')).not.toBeInTheDocument();
});

test('an API error shows the message and request ID (E2E scenario 7)', async () => {
  stubApi({
    '/api/v1/services': () => json(SERVICES),
    '/api/v1/metrics/dora': () =>
      problem(503, 'The database is unavailable. Try again shortly.', 'req-503'),
    '/api/v1/metrics/dora/timeseries': () => json(TIMESERIES),
  });
  renderRoute('/');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('The database is unavailable');
  expect(alert).toHaveTextContent('req-503');
  expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
});

test('filters are sent to the API and kept in the URL', async () => {
  const seen = stubApi({
    '/api/v1/services': () => json(SERVICES),
    '/api/v1/metrics/dora': () => json(summary()),
    '/api/v1/metrics/dora/timeseries': () => json(TIMESERIES),
  });
  const { router } = renderRoute('/');
  await screen.findByRole('article', { name: 'Deployment frequency' });
  const user = userEvent.setup();

  await user.selectOptions(await screen.findByLabelText('Service'), 'Checkout API');
  await user.selectOptions(screen.getByLabelText('Environment'), 'staging');

  await waitFor(() => {
    const last = seen.filter((r) => r.url.includes('/metrics/dora?')).at(-1);
    const params = new URL(last?.url ?? 'http://x').searchParams;
    expect(params.get('environment')).toBe('staging');
    expect(params.get('service_id')).toBe(SERVICES.items[0]?.id);
  });
  expect(router.state.location.search).toContain('env=staging');
  expect(router.state.location.search).toContain(`service=${SERVICES.items[0]?.id ?? ''}`);
});

test('an invalid custom range is explained and not queried', async () => {
  const seen = stubApi({
    '/api/v1/services': () => json(SERVICES),
    '/api/v1/metrics/dora': () => json(summary()),
  });
  renderRoute('/?window=custom&from=2026-09-10&to=2026-09-01');
  expect(await screen.findByRole('alert')).toHaveTextContent('on or after');
  expect(seen.some((r) => r.url.includes('/metrics/dora'))).toBe(false);
});
