/** Display formatting. `null` always renders as an em dash: no data, never 0. */

export const NO_VALUE = '—';

export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return NO_VALUE;
  if (hours < 1) return `${String(Math.round(hours * 60))} min`;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${(hours / 24).toFixed(1)} days`;
}

export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return NO_VALUE;
  return `${(rate * 100).toFixed(1)}%`;
}

/** Deployments per day in the unit that reads naturally for the cadence. */
export function formatFrequency(perDay: number | null | undefined): string {
  if (perDay === null || perDay === undefined) return NO_VALUE;
  if (perDay >= 1) return `${perDay.toFixed(1)} / day`;
  if (perDay >= 1 / 7) return `${(perDay * 7).toFixed(1)} / week`;
  return `${(perDay * 30).toFixed(1)} / month`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

/**
 * A time-series bucket's calendar date. Buckets are defined in UTC (a week
 * starts Monday 00:00 UTC, §7.8), so the label is the UTC date. Rendering it
 * in local time would label a Monday bucket as Sunday west of UTC.
 */
export function formatBucket(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

/** Axis ticks use one fixed unit, unlike formatHours' adaptive h/days/min. */
export function formatAxisHours(hours: number): string {
  return `${String(Math.round(hours))} h`;
}

export function formatAxisPercent(rate: number): string {
  // One decimal only when needed: 2.5% must not read as 3%.
  return `${String(Number((rate * 100).toFixed(1)))}%`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NO_VALUE;
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
