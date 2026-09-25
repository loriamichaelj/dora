/**
 * The one typed API client (§8). Paths and shapes come from the generated
 * OpenAPI types (`make openapi`); nothing here re-declares a response type.
 *
 * Every failure becomes an `ApiError` carrying the RFC 9457 problem body and
 * the response's `X-Request-ID`, so the UI can show field errors inline and
 * quote the request ID for anything else.
 */
import createClient from 'openapi-fetch';

import type { components, paths } from './schema';

export type Schemas = components['schemas'];
export type Problem = Schemas['ProblemDetail'];

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;
  readonly requestId: string | null;

  constructor(status: number, problem: Problem | null, requestId: string | null) {
    super(problem?.detail ?? problem?.title ?? describeStatus(status));
    this.name = 'ApiError';
    this.status = status;
    this.problem = problem;
    this.requestId = requestId;
  }

  /** Field-level validation messages, keyed by field name (e.g. `slug`). */
  get fieldErrors(): Record<string, string> {
    const byField: Record<string, string> = {};
    for (const error of this.problem?.errors ?? []) {
      if (error.location === 'body' && error.field && !(error.field in byField)) {
        byField[error.field] = error.message;
      }
    }
    return byField;
  }

  /** 412: someone else changed the record since it was loaded. */
  get isEditConflict(): boolean {
    return this.status === 412;
  }
}

function describeStatus(status: number): string {
  if (status === 0) return 'The server could not be reached.';
  if (status >= 500) return 'The server had a problem handling this request.';
  return `The request failed (HTTP ${String(status)}).`;
}

function isProblem(value: unknown): value is Problem {
  return (
    typeof value === 'object' &&
    value !== null &&
    'status' in value &&
    'title' in value &&
    typeof (value as { title: unknown }).title === 'string'
  );
}

export const api = createClient<paths>({
  // Always same-origin: nginx (or the Vite dev proxy) routes /api to the API.
  baseUrl: typeof window === 'undefined' ? '' : window.location.origin,
  // Look fetch up per call instead of capturing it at import, so a stubbed
  // or instrumented global fetch is honored.
  fetch: (request) => globalThis.fetch(request),
});

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

export interface Fetched<T> {
  data: T;
  /** The strong ETag, e.g. `"3"`; send it back as If-Match on writes. */
  etag: string | null;
}

/** Resolve an openapi-fetch call to its data, or throw an ApiError. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<Fetched<T>> {
  let result: FetchResult<T>;
  try {
    result = await call;
  } catch {
    throw new ApiError(0, null, null);
  }
  const { data, error, response } = result;
  if (!response.ok || data === undefined) {
    throw new ApiError(
      response.status,
      isProblem(error) ? error : null,
      response.headers.get('x-request-id'),
    );
  }
  return { data, etag: response.headers.get('etag') };
}

/** If-Match for a record's current version (§7.1): always a strong ETag. */
export function ifMatch(version: number): { 'If-Match': string } {
  return { 'If-Match': `"${String(version)}"` };
}
