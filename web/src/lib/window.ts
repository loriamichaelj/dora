/**
 * Dashboard filters, kept in the URL so a view can be bookmarked and shared.
 *
 *   ?service=<uuid>&env=production&window=30
 *   ?window=custom&from=2026-09-01&to=2026-09-30   (local dates, `to` inclusive)
 */
import type { Schemas } from '../api/client';

export type Environment = Schemas['DeploymentOut']['environment'];
export type Preset = '7' | '30' | '90' | 'custom';

export const ENVIRONMENTS: readonly Environment[] = ['production', 'staging', 'development'];
export const PRESETS: readonly { value: Preset; label: string }[] = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
  { value: 'custom', label: 'Custom range' },
];
const MAX_DAYS = 365;
const DAY_MS = 86_400_000;

export interface DashboardFilters {
  serviceId: string | null;
  environment: Environment;
  preset: Preset;
  from: string; // YYYY-MM-DD, used when preset is custom
  to: string;
}

export interface Window {
  from: string; // ISO 8601
  to: string;
}

export function readFilters(params: URLSearchParams): DashboardFilters {
  const env = params.get('env');
  const preset = params.get('window');
  return {
    serviceId: params.get('service') || null,
    environment: ENVIRONMENTS.includes(env as Environment) ? (env as Environment) : 'production',
    preset: PRESETS.some((p) => p.value === preset) ? (preset as Preset) : '30',
    from: params.get('from') ?? '',
    to: params.get('to') ?? '',
  };
}

export function writeFilters(filters: DashboardFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.serviceId) params.set('service', filters.serviceId);
  if (filters.environment !== 'production') params.set('env', filters.environment);
  if (filters.preset !== '30') params.set('window', filters.preset);
  if (filters.preset === 'custom') {
    if (filters.from) params.set('from', filters.from);
    if (filters.to) params.set('to', filters.to);
  }
  return params;
}

function localMidnight(isoDate: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return null;
  const [, y, m, d] = match;
  return new Date(Number(y), Number(m) - 1, Number(d));
}

/**
 * The [from, to) window to query, or an error message for a bad custom range.
 * Presets end at the current minute, so the query key is stable within it.
 */
export function resolveWindow(
  filters: DashboardFilters,
  now: Date = new Date(),
): { window: Window } | { error: string } {
  if (filters.preset !== 'custom') {
    const end = new Date(Math.floor(now.getTime() / 60_000) * 60_000);
    const start = new Date(end.getTime() - Number(filters.preset) * DAY_MS);
    return { window: { from: start.toISOString(), to: end.toISOString() } };
  }
  const start = localMidnight(filters.from);
  const lastDay = localMidnight(filters.to);
  if (!start || !lastDay) return { error: 'Choose both a start and an end date.' };
  const end = new Date(lastDay.getFullYear(), lastDay.getMonth(), lastDay.getDate() + 1);
  if (end <= start) return { error: 'The end date must be on or after the start date.' };
  if (end.getTime() - start.getTime() > MAX_DAYS * DAY_MS) {
    return { error: 'A custom range can span at most 365 days.' };
  }
  return { window: { from: start.toISOString(), to: end.toISOString() } };
}
