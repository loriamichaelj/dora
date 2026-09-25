import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useParams } from 'react-router';

import type { Schemas } from '../api/client';
import { useDoraSummary } from '../api/queries';
import { useDeploymentsPage, useService, useUpdateService } from '../api/resources';
import { KindBadge, StatusBadge } from '../components/Badges';
import { Button, Field, FormActions } from '../components/Form';
import { inputClass } from '../components/formStyles';
import { MetricCards } from '../components/MetricCards';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { useToast } from '../components/toastContext';
import { formatDateTime } from '../lib/format';
import { type EditServiceValues, editServiceSchema } from '../lib/schemas';
import { useMutationErrors } from '../lib/useMutationErrors';
import { resolveWindow } from '../lib/window';
import styles from './Pages.module.css';

const EDIT_FIELDS = ['name', 'owner_team', 'repo_url'] as const;

export function ServiceDetailPage() {
  const { serviceId = '' } = useParams();
  const service = useService(serviceId);

  if (service.isPending) return <LoadingState label="Loading service…" />;
  if (service.isError) {
    return <ErrorState error={service.error} onRetry={() => void service.refetch()} />;
  }
  const s = service.data;
  return (
    <div className={styles.page}>
      <div className={styles.titleRow}>
        <div>
          <h1>{s.name}</h1>
          <p className={styles.subtitle}>
            <span className={styles.mono}>{s.slug}</span> · owned by {s.owner_team}
          </p>
        </div>
        <Link to={`/?service=${s.id}`}>Open in dashboard</Link>
      </div>
      <EditServiceForm service={s} />
      <ServiceMetrics serviceId={s.id} />
      <RecentDeployments serviceId={s.id} />
    </div>
  );
}

function EditServiceForm({ service }: { service: Schemas['ServiceOut'] }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const update = useUpdateService(service.id);
  const defaults = useMemo(
    () => ({
      name: service.name,
      owner_team: service.owner_team,
      repo_url: service.repo_url ?? '',
    }),
    [service.name, service.owner_team, service.repo_url],
  );
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<EditServiceValues>({
    resolver: zodResolver(editServiceSchema),
    defaultValues: defaults,
  });

  // Show the latest saved values whenever the record's version changes.
  useEffect(() => {
    reset(defaults);
  }, [service.version, defaults, reset]);

  const onError = useMutationErrors<EditServiceValues>({
    setError,
    fields: EDIT_FIELDS,
    onConflict: () => {
      void queryClient.invalidateQueries({ queryKey: ['services', 'detail', service.id] });
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await update.mutateAsync({
        version: service.version,
        body: { ...values, repo_url: values.repo_url || null },
      });
      toast.show({ tone: 'success', message: 'Saved.' });
    } catch (error) {
      onError(error);
    }
  });

  return (
    <form
      className={styles.panel}
      aria-label="Edit service"
      noValidate
      onSubmit={(event) => void onSubmit(event)}
    >
      <h2>Details</h2>
      <div className={styles.formGrid}>
        <Field label="Slug" hint="Can't be changed after creation.">
          {(props) => <input {...props} value={service.slug} readOnly className={inputClass} />}
        </Field>
        <Field label="Name" error={errors.name?.message}>
          {(props) => <input {...props} {...register('name')} className={inputClass} />}
        </Field>
        <Field label="Owner team" error={errors.owner_team?.message}>
          {(props) => <input {...props} {...register('owner_team')} className={inputClass} />}
        </Field>
        <Field label="Repository URL" error={errors.repo_url?.message}>
          {(props) => (
            <input {...props} {...register('repo_url')} type="url" className={inputClass} />
          )}
        </Field>
      </div>
      <FormActions>
        <Button type="submit" disabled={isSubmitting || !isDirty}>
          Save changes
        </Button>
        <span className={styles.muted}>Version {service.version}</span>
      </FormActions>
    </form>
  );
}

function ServiceMetrics({ serviceId }: { serviceId: string }) {
  const resolved = resolveWindow({
    serviceId,
    environment: 'production',
    preset: '30',
    from: '',
    to: '',
  });
  const window = 'window' in resolved ? resolved.window : null;
  const summary = useDoraSummary(window ? { serviceId, environment: 'production', window } : null);
  return (
    <section className={styles.page} aria-labelledby="service-metrics">
      <h2 id="service-metrics">DORA metrics · production, last 30 days</h2>
      {summary.isPending ? (
        <LoadingState label="Loading metrics…" />
      ) : summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : summary.data.deployment_frequency.count === 0 ? (
        <EmptyState title="No production deployments in the last 30 days" />
      ) : (
        <MetricCards summary={summary.data} />
      )}
    </section>
  );
}

function RecentDeployments({ serviceId }: { serviceId: string }) {
  const page = useDeploymentsPage({
    serviceId,
    environment: null,
    status: null,
    kind: null,
    from: null,
    to: null,
    offset: 0,
    limit: 10,
  });
  return (
    <section className={styles.panel} aria-labelledby="recent-deployments">
      <div className={styles.titleRow}>
        <h2 id="recent-deployments">Recent deployments</h2>
        <Link to={`/deployments?service=${serviceId}`}>All deployments</Link>
      </div>
      {page.isPending ? (
        <LoadingState label="Loading deployments…" />
      ) : page.isError ? (
        <ErrorState error={page.error} onRetry={() => void page.refetch()} />
      ) : page.data.items.length === 0 ? (
        <EmptyState title="No deployments recorded" />
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Environment</th>
              <th scope="col">Release</th>
              <th scope="col">Status</th>
              <th scope="col">Kind</th>
            </tr>
          </thead>
          <tbody>
            {page.data.items.map((d) => (
              <tr key={d.id}>
                <td>
                  <Link to={`/deployments/${d.id}`}>{formatDateTime(d.started_at)}</Link>
                </td>
                <td>{d.environment}</td>
                <td className={styles.mono}>{d.release}</td>
                <td>
                  <StatusBadge status={d.status} />
                </td>
                <td>
                  <KindBadge kind={d.kind} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
