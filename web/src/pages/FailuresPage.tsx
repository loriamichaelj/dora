import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useSearchParams } from 'react-router';

import type { Schemas } from '../api/client';
import { useServiceOptions } from '../api/queries';
import { PAGE_SIZE, useFailuresPage, useUpdateFailure } from '../api/resources';
import { OpenBadge, SeverityBadge } from '../components/Badges';
import { Dialog } from '../components/Dialog';
import { Button, Field, FormActions } from '../components/Form';
import { inputClass } from '../components/formStyles';
import { Pagination } from '../components/Pagination';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { useToast } from '../components/toastContext';
import { fromLocalInput, nowLocalInput } from '../lib/datetime';
import { formatDateTime } from '../lib/format';
import { type ResolveValues, resolveSchema } from '../lib/schemas';
import { useMutationErrors } from '../lib/useMutationErrors';
import styles from './Pages.module.css';

type Failure = Schemas['FailureOut'];
const OPEN_FILTERS = [
  ['open', 'Open'],
  ['resolved', 'Resolved'],
  ['all', 'All'],
] as const;

export function FailuresPage() {
  const [params, setParams] = useSearchParams();
  const services = useServiceOptions();
  const state = params.get('state') ?? 'open';
  const serviceId = params.get('service');
  const offset = Number(params.get('offset') ?? 0) || 0;
  const page = useFailuresPage({
    open: state === 'all' ? null : state === 'open',
    serviceId,
    offset,
  });
  const [resolving, setResolving] = useState<Failure | null>(null);
  const serviceName = new Map(services.data?.map((s) => [s.id, s.name]) ?? []);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'offset') next.delete('offset');
    setParams(next, { replace: true });
  };

  return (
    <div className={styles.page}>
      <h1>Failures</h1>

      <form
        className={styles.toolbar}
        aria-label="Filters"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <Field label="Status">
          {(props) => (
            <select
              {...props}
              value={state}
              onChange={(e) => {
                setParam('state', e.target.value === 'open' ? '' : e.target.value);
              }}
              className={inputClass}
            >
              {OPEN_FILTERS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Service">
          {(props) => (
            <select
              {...props}
              value={serviceId ?? ''}
              onChange={(e) => {
                setParam('service', e.target.value);
              }}
              className={inputClass}
            >
              <option value="">All services</option>
              {services.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
        </Field>
      </form>

      {page.isPending ? (
        <LoadingState label="Loading failures…" />
      ) : page.isError ? (
        <ErrorState error={page.error} onRetry={() => void page.refetch()} />
      ) : page.data.items.length === 0 ? (
        <EmptyState title={state === 'open' ? 'No open failures' : 'No failures found'} />
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Detected</th>
                  <th scope="col">Service</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Summary</th>
                  <th scope="col">Status</th>
                  <th scope="col">Resolved</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.data.items.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <Link to={`/deployments/${f.deployment_id}`}>
                        {formatDateTime(f.detected_at)}
                      </Link>
                    </td>
                    <td>{serviceName.get(f.service_id) ?? '…'}</td>
                    <td>
                      <SeverityBadge severity={f.severity} />
                    </td>
                    <td>{f.summary}</td>
                    <td>
                      <OpenBadge resolvedAt={f.resolved_at} />
                    </td>
                    <td>{formatDateTime(f.resolved_at)}</td>
                    <td>
                      {!f.resolved_at && (
                        <Button
                          variant="secondary"
                          aria-label={`Resolve: ${f.summary}`}
                          onClick={() => {
                            setResolving(f);
                          }}
                        >
                          Resolve
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            total={page.data.total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={(next) => {
              setParam('offset', next ? String(next) : '');
            }}
          />
        </>
      )}

      <Dialog
        open={resolving !== null}
        title="Resolve failure"
        onClose={() => {
          setResolving(null);
        }}
      >
        {resolving && (
          <ResolveForm
            failure={resolving}
            onClose={() => {
              setResolving(null);
            }}
          />
        )}
      </Dialog>
    </div>
  );
}

function ResolveForm({ failure, onClose }: { failure: Failure; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const update = useUpdateFailure();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ResolveValues>({
    resolver: zodResolver(resolveSchema),
    defaultValues: { resolved_at: nowLocalInput() },
  });
  const onError = useMutationErrors<ResolveValues>({
    setError,
    fields: ['resolved_at'],
    onConflict: () => {
      void queryClient.invalidateQueries({ queryKey: ['failures'] });
      onClose();
    },
  });

  const onSubmit = handleSubmit(async ({ resolved_at }) => {
    try {
      await update.mutateAsync({
        id: failure.id,
        version: failure.version,
        body: { resolved_at: fromLocalInput(resolved_at) ?? resolved_at },
      });
      toast.show({ tone: 'success', message: 'Failure resolved.' });
      onClose();
    } catch (error) {
      onError(error);
    }
  });

  return (
    <form aria-label="Resolve failure" noValidate onSubmit={(event) => void onSubmit(event)}>
      <p>{failure.summary}</p>
      <Field label="Resolved at" error={errors.resolved_at?.message}>
        {(props) => (
          <input
            {...props}
            {...register('resolved_at')}
            type="datetime-local"
            className={inputClass}
          />
        )}
      </Field>
      <FormActions>
        <Button type="submit" disabled={isSubmitting}>
          Resolve
        </Button>
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      </FormActions>
    </form>
  );
}
