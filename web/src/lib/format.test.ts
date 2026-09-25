import {
  formatAxisHours,
  formatAxisPercent,
  formatBucket,
  formatFrequency,
  formatHours,
  formatPercent,
  NO_VALUE,
  plural,
} from './format';

test.each([
  [null, NO_VALUE],
  [0.25, '15 min'],
  [2, '2.0 h'],
  [19, '19.0 h'],
  [47.9, '47.9 h'],
  [72, '3.0 days'],
])('formatHours(%s) = %s', (hours, expected) => {
  expect(formatHours(hours)).toBe(expected);
});

test.each([
  [null, NO_VALUE],
  [0, '0.0%'],
  [0.0596, '6.0%'],
  [0.5, '50.0%'],
])('formatPercent(%s) = %s', (rate, expected) => {
  expect(formatPercent(rate)).toBe(expected);
});

test.each([
  [null, NO_VALUE],
  [4, '4.0 / day'],
  [1, '1.0 / day'],
  [0.1429, '1.0 / week'],
  [0.1333, '4.0 / month'],
])('formatFrequency(%s) = %s', (perDay, expected) => {
  expect(formatFrequency(perDay)).toBe(expected);
});

test('plural', () => {
  expect(plural(1, 'day')).toBe('1 day');
  expect(plural(2, 'day')).toBe('2 days');
  expect(plural(1200, 'commit')).toBe(`${(1200).toLocaleString()} commits`);
});

test('bucket labels are UTC calendar dates, whatever the local zone', () => {
  // Monday 00:00 UTC must never render as the Sunday before.
  expect(formatBucket('2026-08-24T00:00:00Z')).toBe(
    new Date(Date.UTC(2026, 7, 24)).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    }),
  );
  expect(formatBucket('2026-08-24T00:00:00Z')).toContain('24');
});

test('axis formats use one fixed unit', () => {
  expect(formatAxisHours(79.2)).toBe('79 h');
  expect(formatAxisHours(0)).toBe('0 h');
  expect(formatAxisPercent(0.075)).toBe('7.5%');
  expect(formatAxisPercent(0.1)).toBe('10%');
});
