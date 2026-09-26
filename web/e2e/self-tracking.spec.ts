/** §12.4 scenario 10: self-tracking through the public ingest API (§15). */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import { INGEST_KEY, REPO_ROOT } from './support';

const BASE = process.env.E2E_BASE_URL ?? 'http://localhost:18080';

function git(cwd: string, ...args: string[]): string {
  return execFileSync('git', args, { cwd, encoding: 'utf8' }).trim();
}

/** Run the real script on the host, as `make up` does. */
function recordDeploy(repo: string): string {
  return execFileSync(
    'python3',
    [
      path.join(REPO_ROOT, 'scripts/record_deploy.py'),
      '--repo',
      repo,
      '--api-url',
      BASE,
      '--api-key',
      INGEST_KEY,
      // The E2E stack was built from this repo, not the clone, so /version
      // can't match the clone's HEAD; state the outcome explicitly.
      '--status',
      'succeeded',
    ],
    { encoding: 'utf8' },
  );
}

test('10. record_deploy.py records one development deployment per build of a clone', async ({
  page,
  request,
}) => {
  const workdir = mkdtempSync(path.join(tmpdir(), 'dora-e2e-clone-'));
  const clone = path.join(workdir, 'repo');
  try {
    git(workdir, 'clone', '--quiet', REPO_ROOT, clone);
    git(clone, 'config', 'user.email', 'e2e@example.com');
    git(clone, 'config', 'user.name', 'E2E');
    git(clone, 'config', 'commit.gpgsign', 'false');

    // Baseline: the first recorded build records HEAD only (§15.3).
    expect(recordDeploy(clone)).toContain('first recorded build');
    const baseline = git(clone, 'rev-parse', 'HEAD');

    for (const n of [1, 2]) {
      writeFileSync(path.join(clone, `e2e-change-${String(n)}.txt`), `change ${String(n)}\n`);
      git(clone, 'add', '.');
      git(clone, 'commit', '--quiet', '-m', `e2e: change ${String(n)}`);
    }
    const head = git(clone, 'rev-parse', 'HEAD');
    const expected = git(clone, 'log', '--format=%H', `${baseline}..${head}`).split('\n');
    expect(expected).toHaveLength(2);

    expect(recordDeploy(clone)).toContain('recording 2 commit(s)');

    // Through the API: one deployment for this build, carrying exactly those commits.
    const services = (await (await request.get('/api/v1/services?q=dora-tracker')).json()) as {
      items: { id: string; slug: string }[];
    };
    const tracker = services.items.find((s) => s.slug === 'dora-tracker');
    expect(tracker).toBeDefined();
    const list = (await (
      await request.get(
        `/api/v1/deployments?service_id=${tracker?.id ?? ''}&environment=development&limit=200`,
      )
    ).json()) as { total: number; items: { id: string; head_sha: string | null }[] };
    const forHead = list.items.filter((d) => d.head_sha === head);
    expect(forHead).toHaveLength(1);
    const detail = (await (
      await request.get(`/api/v1/deployments/${forHead[0]?.id ?? ''}`)
    ).json()) as { status: string; commits: { sha: string }[] };
    expect(detail.status).toBe('succeeded');
    // Same commits as `git log`. Order isn't compared: commits made in the same
    // second share committed_at, and the API breaks such ties by SHA (D37).
    expect(detail.commits.map((c) => c.sha).sort()).toEqual([...expected].sort());

    // Running it again for the same build records nothing new.
    expect(recordDeploy(clone)).toContain('already recorded');
    const again = (await (
      await request.get(
        `/api/v1/deployments?service_id=${tracker?.id ?? ''}&environment=development&limit=200`,
      )
    ).json()) as { total: number };
    expect(again.total).toBe(list.total);

    // And the UI shows it.
    await page.goto(`/deployments/${forHead[0]?.id ?? ''}`);
    await expect(page.getByRole('region', { name: 'Commits (2)' })).toBeVisible();
  } finally {
    rmSync(workdir, { recursive: true, force: true });
  }
});
