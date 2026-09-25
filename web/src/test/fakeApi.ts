/**
 * A fetch stub for component tests: routes by path, answers with JSON (or
 * problem+json), and records every request. Fixtures are typed from the
 * generated schema, so a contract change breaks the tests that depend on it.
 */
import { vi } from 'vitest';

import type { Schemas } from '../api/client';

export type Handler = (url: URL, request: Request) => Response | Promise<Response>;

export function json(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'content-type': 'application/json', ...init.headers },
  });
}

export function problem(status: number, detail: string, requestId = 'req-test-1'): Response {
  return new Response(
    JSON.stringify({ type: 'about:blank', title: 'Error', status, detail, instance: '/x' }),
    {
      status,
      headers: { 'content-type': 'application/problem+json', 'x-request-id': requestId },
    },
  );
}

export function stubApi(routes: Record<string, Handler>): Request[] {
  const seen: Request[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      seen.push(request);
      const url = new URL(request.url);
      const handler = routes[url.pathname];
      if (!handler) return problem(404, `No stub for ${url.pathname}`);
      return handler(url, request);
    }),
  );
  return seen;
}

export const SERVICES: Schemas['Page_ServiceOut_'] = {
  items: [
    {
      id: '019f0000-0000-7000-8000-000000000001',
      slug: 'checkout-api',
      name: 'Checkout API',
      owner_team: 'payments',
      repo_url: null,
      version: 1,
      created_at: '2026-09-01T00:00:00Z',
      updated_at: '2026-09-01T00:00:00Z',
    },
  ],
  total: 1,
  limit: 200,
  offset: 0,
};

export function summary(overrides: Partial<Schemas['DoraSummary']> = {}): Schemas['DoraSummary'] {
  return {
    window: { from: '2026-09-01T00:00:00Z', to: '2026-10-01T00:00:00Z', days: 30 },
    filters: { service_id: null, environment: 'production' },
    band_set: 'dora-2023-adapted',
    deployment_frequency: { count: 4, per_day: 0.1333, deploy_days: 4, band: 'medium' },
    change_lead_time: {
      median_hours: 19,
      p90_hours: 24,
      sample_size: 4,
      excluded_samples: 0,
      band: 'elite',
    },
    change_fail_rate: { rate: 0.5, failed_deployments: 2, total_deployments: 4, band: 'low' },
    failed_deployment_recovery_time: {
      median_hours: 2,
      sample_size: 2,
      open_failures: 1,
      band: 'high',
    },
    deployment_rework_rate: {
      rate: 0.25,
      remediation_deployments: 1,
      total_deployments: 4,
      band: null,
    },
    ...overrides,
  };
}

export const EMPTY_SUMMARY = summary({
  deployment_frequency: { count: 0, per_day: null, deploy_days: 0, band: null },
  change_lead_time: {
    median_hours: null,
    p90_hours: null,
    sample_size: 0,
    excluded_samples: 0,
    band: null,
  },
  change_fail_rate: { rate: null, failed_deployments: 0, total_deployments: 0, band: null },
  failed_deployment_recovery_time: {
    median_hours: null,
    sample_size: 0,
    open_failures: 0,
    band: null,
  },
  deployment_rework_rate: {
    rate: null,
    remediation_deployments: 0,
    total_deployments: 0,
    band: null,
  },
});

export const TIMESERIES: Schemas['DoraTimeseries'] = {
  window: { from: '2026-09-01T00:00:00Z', to: '2026-10-01T00:00:00Z', days: 30 },
  filters: { service_id: null, environment: 'production' },
  bucket: 'week',
  points: [
    {
      start: '2026-08-31T00:00:00Z',
      deployment_count: 2,
      median_lead_time_hours: 18,
      change_fail_rate: 0.5,
      median_recovery_hours: 2,
      rework_rate: 0,
    },
    {
      start: '2026-09-07T00:00:00Z',
      deployment_count: 0,
      median_lead_time_hours: null,
      change_fail_rate: null,
      median_recovery_hours: null,
      rework_rate: null,
    },
  ],
};
