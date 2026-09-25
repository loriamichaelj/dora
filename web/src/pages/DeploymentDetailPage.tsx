import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import type { Schemas } from '../api/client';
import { useDeployment, useService, useUpdateDeployment } from '../api/resources';
import { KindBadge, OpenBadge, SeverityBadge, StatusBadge } from '../components/Badges';
import { Button, FormActions } from '../components/Form';
import { RecordFailureDialog } from '../components/RecordFailureDialog';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { useToast } from '../components/toastContext';
import { formatDateTime, NO_VALUE } from '../lib/format';
import { useMutationErrors } from '../lib/useMutationErrors';
import styles from './Pages.module.css';

type Deployment = Schemas['DeploymentDetail'];
type Status = Deployment['status'];

/**
 * The only moves §7.7 allows through the UI. Anything else (including the
 * "stale" backward moves only ingest tolerates) is never offered.
 */
const TRANSITIONS: Record<Status, readonly { to: Status; label: string }[]> = {
  in_progress: [
    { to: 'succeeded', label: 'Mark succeeded' },
    { to: 'failed', label: 'Mark failed' },
  ],
  succeeded: [{ to: 'rolled_back', label: 'Mark rolled back' }],
  failed: [],
  rolled_back: [],
};
const LIVE: readonly Status[] = ['succeeded', 'rolled_back'];

export function DeploymentDetailPage() {
  const { deploymentId = '' } = useParams();
  const deployment = useDeployment(deploymentId);

  if (deployment.isPending) return <LoadingState label="Loading deployment…" />;
  if (deployment.isError) {
    return <ErrorState error={deployment.error} onRetry={() => void deployment.refetch()} />;
  }
  return <DeploymentView deployment={deployment.data} />;
}

function DeploymentView({ deployment: d }: { deployment: Deployment }) {
  const service = useService(d.service_id);
  const toast = useToast();
  const queryClient = useQueryClient();
  const update = useUpdateDeployment(d.id);
  const [failureDialog, setFailureDialog] = useState<'closed' | 'manual' | 'afterRollback'>(
    'closed',
  );
  const onError = useMutationErrors({
    onConflict: () => {
      void queryClient.invalidateQueries({ queryKey: ['deployments', 'detail', d.id] });
    },
  });

  const transition = async (to: Status) => {
    const body: Schemas['DeploymentUpdate'] = { status: to };
    if (d.status === 'in_progress') body.finished_at = new Date().toISOString();
    try {
      await update.mutateAsync({ version: d.version, body });
      toast.show({ tone: 'success', message: `Marked ${to.replace('_', ' ')}.` });
      if (to === 'rolled_back') setFailureDialog('afterRollback');
    } catch (error) {
      onError(error);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.titleRow}>
        <div>
          <h1 className={styles.monoInherit}>{d.release}</h1>
          <p className={styles.subtitle}>
            {service.data ? <Link to={`/services/${d.service_id}`}>{service.data.name}</Link> : '…'}{' '}
            · {d.environment}
          </p>
        </div>
        <div className={styles.badges}>
          <StatusBadge status={d.status} />
          <KindBadge kind={d.kind} />
        </div>
      </div>

      <section className={styles.panel} aria-labelledby="deployment-details">
        <h2 id="deployment-details">Details</h2>
        <dl className={styles.details}>
          <dt>Started</dt>
          <dd>{formatDateTime(d.started_at)}</dd>
          <dt>Finished</dt>
          <dd>{formatDateTime(d.finished_at)}</dd>
          <dt>Head commit</dt>
          <dd className={styles.mono}>{d.head_sha ?? NO_VALUE}</dd>
          <dt>Deployed by</dt>
          <dd>{d.deployed_by ?? NO_VALUE}</dd>
          <dt>Pipeline</dt>
          <dd>
            {d.pipeline_url ? (
              <a href={d.pipeline_url} rel="noreferrer noopener" target="_blank">
                {d.pipeline_url}
              </a>
            ) : (
              NO_VALUE
            )}
          </dd>
          <dt>External ID</dt>
          <dd className={styles.mono}>{d.external_id ?? NO_VALUE}</dd>
          <dt>Version</dt>
          <dd>{d.version}</dd>
        </dl>
        {(TRANSITIONS[d.status].length > 0 || LIVE.includes(d.status)) && (
          <FormActions>
            {TRANSITIONS[d.status].map((t) => (
              <Button
                key={t.to}
                variant={t.to === 'succeeded' ? 'primary' : 'secondary'}
                disabled={update.isPending}
                onClick={() => void transition(t.to)}
              >
                {t.label}
              </Button>
            ))}
            {LIVE.includes(d.status) && (
              <Button
                variant="secondary"
                onClick={() => {
                  setFailureDialog('manual');
                }}
              >
                Record failure
              </Button>
            )}
          </FormActions>
        )}
      </section>

      <section className={styles.panel} aria-labelledby="deployment-failures">
        <h2 id="deployment-failures">Failures</h2>
        {d.failures.length === 0 ? (
          <p className={styles.muted}>No failures recorded against this deployment.</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Severity</th>
                <th scope="col">Summary</th>
                <th scope="col">Detected</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {d.failures.map((f) => (
                <tr key={f.id}>
                  <td>
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td>{f.summary}</td>
                  <td>{formatDateTime(f.detected_at)}</td>
                  <td>
                    <OpenBadge resolvedAt={f.resolved_at} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={styles.panel} aria-labelledby="deployment-commits">
        <h2 id="deployment-commits">Commits ({d.commits.length})</h2>
        {d.commits.length === 0 ? (
          <EmptyState title="No commits linked" />
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">SHA</th>
                <th scope="col">Message</th>
                <th scope="col">Author</th>
                <th scope="col">Committed</th>
              </tr>
            </thead>
            <tbody>
              {d.commits.map((c) => (
                <tr key={c.id}>
                  <td className={styles.mono} title={c.sha}>
                    {c.sha.slice(0, 7)}
                  </td>
                  <td>{c.message ?? NO_VALUE}</td>
                  <td>{c.author ?? NO_VALUE}</td>
                  <td>{formatDateTime(c.committed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <RecordFailureDialog
        open={failureDialog !== 'closed'}
        deploymentId={d.id}
        afterRollback={failureDialog === 'afterRollback'}
        onClose={() => {
          setFailureDialog('closed');
        }}
      />
    </div>
  );
}
