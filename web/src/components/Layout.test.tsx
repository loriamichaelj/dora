import { screen } from '@testing-library/react';

import { json, SERVICES, stubApi } from '../test/fakeApi';
import { renderRoute } from '../test/render';

const SHA = '2df9ba27a031792fd99112f1f8b70de5f8fe842d';

test('the footer shows the running version and commit', async () => {
  stubApi({
    '/version': () => json({ version: '0.1.0', git_sha: SHA, build_time: '2026-09-26T23:59:02Z' }),
    '/api/v1/services': () => json(SERVICES),
  });
  renderRoute('/services');
  const footer = await screen.findByRole('contentinfo');
  expect(footer).toHaveTextContent('DORA Tracker 0.1.0 · 2df9ba2');
  expect(screen.getByTitle(SHA)).toBeInTheDocument();
});

test('the footer stays hidden when /version is unavailable', async () => {
  stubApi({ '/api/v1/services': () => json(SERVICES) });
  renderRoute('/services');
  await screen.findByRole('heading', { name: 'Services' });
  expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
});
