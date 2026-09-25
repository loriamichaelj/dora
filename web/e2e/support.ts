/** Helpers shared by the E2E scenarios. */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { type APIRequestContext, expect } from '@playwright/test';

export const REPO_ROOT = path.resolve(import.meta.dirname, '../..');
const ENV_FILE = path.join(REPO_ROOT, 'web/e2e/e2e.env');
export const PROJECT = 'dora-e2e';

function readEnvFile(): Record<string, string> {
  const values: Record<string, string> = {};
  for (const line of readFileSync(ENV_FILE, 'utf8').split('\n')) {
    const match = /^([A-Z_]+)=(.*)$/.exec(line.trim());
    if (match?.[1]) values[match[1]] = match[2] ?? '';
  }
  return values;
}

export const E2E_ENV = readEnvFile();
export const INGEST_KEY = E2E_ENV.INGEST_API_KEY ?? '';

/** `docker compose` against the isolated E2E project only. */
export function compose(...args: string[]): string {
  return execFileSync(
    'docker',
    ['compose', '-p', PROJECT, '--env-file', ENV_FILE, '-f', 'compose.yaml', ...args],
    { cwd: REPO_ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
  );
}

export function containerState(service: string): { startedAt: string; health: string } {
  const id = compose('ps', '-q', service).trim();
  const out = execFileSync(
    'docker',
    ['inspect', '--format', '{{.State.StartedAt}}|{{.State.Health.Status}}', id],
    { encoding: 'utf8' },
  ).trim();
  const [startedAt = '', health = ''] = out.split('|');
  return { startedAt, health };
}

/** A slug no other test (or earlier run) uses. */
export function uniqueSlug(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

export interface Service {
  id: string;
  slug: string;
  name: string;
  version: number;
}

export async function createService(
  request: APIRequestContext,
  slug: string,
  name = slug,
): Promise<Service> {
  const resp = await request.post('/api/v1/services', {
    data: { slug, name, owner_team: 'e2e' },
  });
  expect(resp.status(), await resp.text()).toBe(201);
  return (await resp.json()) as Service;
}

export interface DeploymentEvent {
  service_slug: string;
  external_id: string;
  environment?: 'production' | 'staging' | 'development';
  release?: string;
  status: 'in_progress' | 'succeeded' | 'failed' | 'rolled_back';
  started_at: string;
  finished_at?: string;
  commits?: { sha: string; committed_at: string }[];
}

export async function ingest(request: APIRequestContext, event: DeploymentEvent) {
  const resp = await request.post('/api/v1/events/deployments', {
    headers: { 'X-API-Key': INGEST_KEY },
    data: { environment: 'production', release: 'v1.0.0', ...event },
  });
  return { status: resp.status(), body: (await resp.json()) as Record<string, unknown> };
}

export function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}
