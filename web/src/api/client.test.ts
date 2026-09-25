import { vi } from 'vitest';

import { json, stubApi } from '../test/fakeApi';
import { api, ApiError, ifMatch, unwrap } from './client';

/** Await a call that must fail, returning its ApiError. */
async function failure(call: Promise<unknown>): Promise<ApiError> {
  try {
    await call;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error('expected the call to fail');
}

const ID = '019f0000-0000-7000-8000-000000000001';

test('returns data and the strong ETag', async () => {
  stubApi({
    [`/api/v1/services/${ID}`]: () =>
      json({ id: ID, slug: 's', version: 3 }, { headers: { etag: '"3"' } }),
  });
  const result = await unwrap(
    api.GET('/api/v1/services/{service_id}', { params: { path: { service_id: ID } } }),
  );
  expect(result.etag).toBe('"3"');
  expect(result.data.version).toBe(3);
});

test('problem+json becomes an ApiError with field errors and the request ID', async () => {
  stubApi({
    '/api/v1/services': () =>
      new Response(
        JSON.stringify({
          type: 'urn:dora:problem:conflict',
          title: 'Conflict',
          status: 409,
          detail: "A service with slug 'x' already exists.",
          instance: '/api/v1/services',
          errors: [{ location: 'body', field: 'slug', message: 'In use.', type: 'unique' }],
        }),
        {
          status: 409,
          headers: { 'content-type': 'application/problem+json', 'x-request-id': 'req-9' },
        },
      ),
  });
  const apiError = await failure(
    unwrap(api.POST('/api/v1/services', { body: { slug: 'x', name: 'X', owner_team: 't' } })),
  );
  expect(apiError.status).toBe(409);
  expect(apiError.message).toBe("A service with slug 'x' already exists.");
  expect(apiError.requestId).toBe('req-9');
  expect(apiError.fieldErrors).toEqual({ slug: 'In use.' });
  expect(apiError.isEditConflict).toBe(false);
});

test('412 is an edit conflict', async () => {
  stubApi({
    [`/api/v1/services/${ID}`]: () =>
      new Response(JSON.stringify({ type: 'x', title: 'Precondition Failed', status: 412 }), {
        status: 412,
        headers: { 'content-type': 'application/problem+json' },
      }),
  });
  const error = await failure(
    unwrap(
      api.PATCH('/api/v1/services/{service_id}', {
        params: { path: { service_id: ID }, header: ifMatch(1) },
        body: { name: 'New' },
      }),
    ),
  );
  expect(error.isEditConflict).toBe(true);
});

test('sends If-Match as a strong ETag', async () => {
  const seen = stubApi({ [`/api/v1/services/${ID}`]: () => json({ id: ID }) });
  await unwrap(
    api.PATCH('/api/v1/services/{service_id}', {
      params: { path: { service_id: ID }, header: ifMatch(7) },
      body: { name: 'New' },
    }),
  );
  expect(seen[0]?.headers.get('if-match')).toBe('"7"');
});

test('a network failure is status 0 with a readable message', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
  const error = await failure(unwrap(api.GET('/api/v1/services')));
  expect(error.status).toBe(0);
  expect(error.message).toMatch(/could not be reached/);
});

test('a non-JSON error body still yields an ApiError', async () => {
  stubApi({
    '/api/v1/services': () =>
      new Response('<html>Bad Gateway</html>', {
        status: 502,
        headers: { 'content-type': 'text/html' },
      }),
  });
  const error = await failure(unwrap(api.GET('/api/v1/services')));
  expect(error.status).toBe(502);
  expect(error.problem).toBeNull();
  expect(error.message).toMatch(/server had a problem/);
});
