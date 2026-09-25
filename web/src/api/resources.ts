/**
 * Queries and mutations for services, deployments, and failures.
 *
 * Writes send If-Match with the version the user was looking at (§7.1).
 * After any write, every view that could show the changed data (lists,
 * details, and DORA metrics) is invalidated.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ifMatch, type Schemas, unwrap } from './client';

export const PAGE_SIZE = 25;

// ---- services ----

export interface ServiceListQuery {
  q: string;
  offset: number;
}

export function useServicesPage({ q, offset }: ServiceListQuery) {
  return useQuery({
    queryKey: ['services', 'list', { q, offset }],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/services', {
            params: { query: { ...(q ? { q } : {}), limit: PAGE_SIZE, offset, sort: 'name' } },
          }),
        )
      ).data,
  });
}

export function useService(id: string) {
  return useQuery({
    queryKey: ['services', 'detail', id],
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/services/{service_id}', { params: { path: { service_id: id } } }),
        )
      ).data,
  });
}

export function useCreateService() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas['ServiceCreate']) =>
      (await unwrap(api.POST('/api/v1/services', { body }))).data,
    onSuccess: () => client.invalidateQueries({ queryKey: ['services'] }),
  });
}

export function useUpdateService(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ version, body }: { version: number; body: Schemas['ServiceUpdate'] }) =>
      (
        await unwrap(
          api.PATCH('/api/v1/services/{service_id}', {
            params: { path: { service_id: id }, header: ifMatch(version) },
            body,
          }),
        )
      ).data,
    onSettled: () => client.invalidateQueries({ queryKey: ['services'] }),
  });
}

// ---- deployments ----

export type DeploymentStatus = Schemas['DeploymentOut']['status'];
export type DeploymentKind = Schemas['DeploymentOut']['kind'];
export type Environment = Schemas['DeploymentOut']['environment'];

export interface DeploymentListQuery {
  serviceId: string | null;
  environment: Environment | null;
  status: DeploymentStatus | null;
  kind: DeploymentKind | null;
  from: string | null; // ISO
  to: string | null;
  offset: number;
  limit?: number;
}

export function useDeploymentsPage(query: DeploymentListQuery) {
  return useQuery({
    queryKey: ['deployments', 'list', query],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/deployments', {
            params: {
              query: {
                ...(query.serviceId ? { service_id: query.serviceId } : {}),
                ...(query.environment ? { environment: query.environment } : {}),
                ...(query.status ? { status: query.status } : {}),
                ...(query.kind ? { kind: query.kind } : {}),
                ...(query.from ? { from: query.from } : {}),
                ...(query.to ? { to: query.to } : {}),
                limit: query.limit ?? PAGE_SIZE,
                offset: query.offset,
              },
            },
          }),
        )
      ).data,
  });
}

export function useDeployment(id: string) {
  return useQuery({
    queryKey: ['deployments', 'detail', id],
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/deployments/{deployment_id}', {
            params: { path: { deployment_id: id } },
          }),
        )
      ).data,
  });
}

function useInvalidateDeliveryData() {
  const client = useQueryClient();
  return () =>
    Promise.all(
      ['deployments', 'failures', 'metrics'].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    );
}

export function useCreateDeployment() {
  const invalidate = useInvalidateDeliveryData();
  return useMutation({
    mutationFn: async (body: Schemas['DeploymentCreate']) =>
      (await unwrap(api.POST('/api/v1/deployments', { body }))).data,
    onSuccess: invalidate,
  });
}

export function useUpdateDeployment(id: string) {
  const invalidate = useInvalidateDeliveryData();
  return useMutation({
    mutationFn: async ({ version, body }: { version: number; body: Schemas['DeploymentUpdate'] }) =>
      (
        await unwrap(
          api.PATCH('/api/v1/deployments/{deployment_id}', {
            params: { path: { deployment_id: id }, header: ifMatch(version) },
            body,
          }),
        )
      ).data,
    onSettled: invalidate,
  });
}

// ---- failures ----

export interface FailureListQuery {
  open: boolean | null;
  serviceId: string | null;
  offset: number;
}

export function useFailuresPage({ open, serviceId, offset }: FailureListQuery) {
  return useQuery({
    queryKey: ['failures', 'list', { open, serviceId, offset }],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/failures', {
            params: {
              query: {
                ...(open === null ? {} : { open }),
                ...(serviceId ? { service_id: serviceId } : {}),
                limit: PAGE_SIZE,
                offset,
              },
            },
          }),
        )
      ).data,
  });
}

export function useCreateFailure() {
  const invalidate = useInvalidateDeliveryData();
  return useMutation({
    mutationFn: async (body: Schemas['FailureCreate']) =>
      (await unwrap(api.POST('/api/v1/failures', { body }))).data,
    onSuccess: invalidate,
  });
}

export function useUpdateFailure() {
  const invalidate = useInvalidateDeliveryData();
  return useMutation({
    mutationFn: async ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: Schemas['FailureUpdate'];
    }) =>
      (
        await unwrap(
          api.PATCH('/api/v1/failures/{failure_id}', {
            params: { path: { failure_id: id }, header: ifMatch(version) },
            body,
          }),
        )
      ).data,
    onSettled: invalidate,
  });
}
