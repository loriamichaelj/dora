import { readFilters, resolveWindow, writeFilters } from './window';

const NOW = new Date('2026-09-25T12:34:56.789Z');

test('defaults: production, last 30 days, all services', () => {
  expect(readFilters(new URLSearchParams())).toEqual({
    serviceId: null,
    environment: 'production',
    preset: '30',
    from: '',
    to: '',
  });
});

test('unknown values fall back to defaults', () => {
  const filters = readFilters(new URLSearchParams('env=prod&window=365'));
  expect(filters.environment).toBe('production');
  expect(filters.preset).toBe('30');
});

test('filters round-trip through the URL, omitting defaults', () => {
  const filters = readFilters(
    new URLSearchParams('service=abc&env=staging&window=custom&from=2026-09-01&to=2026-09-30'),
  );
  expect(writeFilters(filters).toString()).toBe(
    'service=abc&env=staging&window=custom&from=2026-09-01&to=2026-09-30',
  );
  expect(writeFilters(readFilters(new URLSearchParams())).toString()).toBe('');
});

test('presets end at the end of the current minute, so just-finished work counts', () => {
  const result = resolveWindow(readFilters(new URLSearchParams('window=7')), NOW);
  expect(result).toEqual({
    window: { from: '2026-09-18T12:35:00.000Z', to: '2026-09-25T12:35:00.000Z' },
  });
  // Exactly on a minute boundary, that minute is still included.
  const onBoundary = resolveWindow(
    readFilters(new URLSearchParams('window=7')),
    new Date('2026-09-25T12:34:00.000Z'),
  );
  expect(onBoundary).toEqual({
    window: { from: '2026-09-18T12:35:00.000Z', to: '2026-09-25T12:35:00.000Z' },
  });
});

test('custom ranges include the whole last day, in local time', () => {
  const result = resolveWindow(
    readFilters(new URLSearchParams('window=custom&from=2026-09-01&to=2026-09-30')),
  );
  expect(result).toEqual({
    window: {
      from: new Date(2026, 8, 1).toISOString(),
      to: new Date(2026, 9, 1).toISOString(),
    },
  });
});

test.each([
  ['window=custom', 'Choose both'],
  ['window=custom&from=2026-09-10&to=2026-09-01', 'on or after'],
  ['window=custom&from=2025-01-01&to=2026-09-01', '365 days'],
])('invalid custom range %s', (query, message) => {
  const result = resolveWindow(readFilters(new URLSearchParams(query)));
  expect(result).toEqual({ error: expect.stringContaining(message) as string });
});
