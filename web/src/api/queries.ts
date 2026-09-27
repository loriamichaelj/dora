/** TanStack Query hooks over the typed client. */
import { keepPreviousData, QueryClient, useQuery } from '@tanstack/react-query';

import type { Environment, Window } from '../lib/window';
import { api, ApiError, unwrap } from './client';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // A 4xx won't fix itself; a 503 (database blip) often does.
        retry: (failures, error) =>
          failures < 2 && (!(error instanceof ApiError) || error.status >= 500),
      },
    },
  });
}

export function useServiceOptions() {
  return useQuery({
    queryKey: ['services', 'options'],
    queryFn: async () => {
      const { data } = await unwrap(
        api.GET('/api/v1/services', { params: { query: { limit: 200, sort: 'name' } } }),
      );
      return data.items;
    },
  });
}

export interface MetricsQuery {
  serviceId: string | null;
  environment: Environment;
  window: Window;
}

function metricsParams({ serviceId, environment, window }: MetricsQuery) {
  return {
    environment,
    from: window.from,
    to: window.to,
    ...(serviceId ? { service_id: serviceId } : {}),
  };
}

export function useDoraSummary(query: MetricsQuery | null) {
  return useQuery({
    queryKey: ['metrics', 'summary', query],
    enabled: query !== null,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      if (!query) throw new Error('unreachable: disabled without a query');
      const { data } = await unwrap(
        api.GET('/api/v1/metrics/dora', { params: { query: metricsParams(query) } }),
      );
      return data;
    },
  });
}

export function useDoraTimeseries(query: MetricsQuery | null) {
  return useQuery({
    queryKey: ['metrics', 'timeseries', query],
    enabled: query !== null,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      if (!query) throw new Error('unreachable: disabled without a query');
      const { data } = await unwrap(
        api.GET('/api/v1/metrics/dora/timeseries', {
          params: { query: { ...metricsParams(query), bucket: 'week' } },
        }),
      );
      return data;
    },
  });
}

/** What's running: the app version and the commit it was built from. */
export function useVersion() {
  return useQuery({
    queryKey: ['version'],
    queryFn: async () => (await unwrap(api.GET('/version'))).data,
    staleTime: Infinity,
    retry: false,
  });
}
