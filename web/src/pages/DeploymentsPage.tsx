import { Link, useSearchParams } from 'react-router';

import { useServiceOptions } from '../api/queries';
import {
  type DeploymentKind,
  type DeploymentStatus,
  type Environment,
  PAGE_SIZE,
  useDeploymentsPage,
} from '../api/resources';
import { KindBadge, StatusBadge } from '../components/Badges';
import { Field } from '../components/Form';
import { inputClass } from '../components/formStyles';
import { Pagination } from '../components/Pagination';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { cx } from '../lib/cx';
import { formatDateTime } from '../lib/format';
import { STATUS_LABELS } from '../lib/labels';
import { ENVIRONMENTS, KINDS, STATUSES } from '../lib/schemas';
import styles from './Pages.module.css';

/** YYYY-MM-DD (local) -> ISO for local midnight; `endOfDay` gives the next midnight. */
function dayToIso(day: string, endOfDay = false): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return null;
  const [, y, m, d] = match;
  return new Date(Number(y), Number(m) - 1, Number(d) + (endOfDay ? 1 : 0)).toISOString();
}

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return allowed.includes(value as T) ? (value as T) : null;
}

export function DeploymentsPage() {
  const [params, setParams] = useSearchParams();
  const services = useServiceOptions();
  const filters = {
    serviceId: params.get('service'),
    environment: pick<Environment>(params.get('env'), ENVIRONMENTS),
    status: pick<DeploymentStatus>(params.get('status'), STATUSES),
    kind: pick<DeploymentKind>(params.get('kind'), KINDS),
    fromDay: params.get('from') ?? '',
    toDay: params.get('to') ?? '',
  };
  const offset = Number(params.get('offset') ?? 0) || 0;
  const page = useDeploymentsPage({
    serviceId: filters.serviceId,
    environment: filters.environment,
    status: filters.status,
    kind: filters.kind,
    from: dayToIso(filters.fromDay),
    to: dayToIso(filters.toDay, true),
    offset,
  });
  const serviceName = new Map(services.data?.map((s) => [s.id, s.name]) ?? []);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'offset') next.delete('offset');
    setParams(next, { replace: true });
  };

  const select = (key: string, label: string, options: readonly (readonly [string, string])[]) => (
    <Field label={label}>
      {(props) => (
        <select
          {...props}
          value={params.get(key) ?? ''}
          onChange={(e) => {
            setParam(key, e.target.value);
          }}
          className={inputClass}
        >
          <option value="">All</option>
          {options.map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
      )}
    </Field>
  );

  return (
    <div className={styles.page}>
      <div className={styles.titleRow}>
        <div>
          <h1>Deployments</h1>
          <p className={styles.subtitle}>Every release to every environment, newest first.</p>
        </div>
      </div>

      <form
        className={styles.toolbar}
        aria-label="Filters"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        {select(
          'service',
          'Service',
          (services.data ?? []).map((s) => [s.id, s.name] as const),
        )}
        {select(
          'env',
          'Environment',
          ENVIRONMENTS.map((e) => [e, e] as const),
        )}
        {select(
          'status',
          'Status',
          STATUSES.map((s) => [s, STATUS_LABELS[s]] as const),
        )}
        {select(
          'kind',
          'Kind',
          KINDS.map((k) => [k, k === 'planned' ? 'Planned' : 'Remediation'] as const),
        )}
        <Field label="Started from">
          {(props) => (
            <input
              {...props}
              type="date"
              value={filters.fromDay}
              onChange={(e) => {
                setParam('from', e.target.value);
              }}
              className={inputClass}
            />
          )}
        </Field>
        <Field label="Started to">
          {(props) => (
            <input
              {...props}
              type="date"
              value={filters.toDay}
              onChange={(e) => {
                setParam('to', e.target.value);
              }}
              className={inputClass}
            />
          )}
        </Field>
      </form>

      {page.isPending ? (
        <LoadingState label="Loading deployments…" />
      ) : page.isError ? (
        <ErrorState error={page.error} onRetry={() => void page.refetch()} />
      ) : page.data.items.length === 0 ? (
        <EmptyState title="No deployments match these filters" />
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Service</th>
                  <th scope="col">Environment</th>
                  <th scope="col">Release</th>
                  <th scope="col">Status</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Finished</th>
                </tr>
              </thead>
              <tbody>
                {page.data.items.map((d) => (
                  <tr key={d.id}>
                    <td className={cx(styles.primaryCell, styles.nowrap)}>
                      <Link to={`/deployments/${d.id}`}>{formatDateTime(d.started_at)}</Link>
                    </td>
                    <td>{serviceName.get(d.service_id) ?? '…'}</td>
                    <td>
                      <span className={styles.env}>{d.environment}</span>
                    </td>
                    <td className={styles.mono}>{d.release}</td>
                    <td>
                      <StatusBadge status={d.status} />
                    </td>
                    <td>
                      <KindBadge kind={d.kind} />
                    </td>
                    <td className={cx(styles.muted, styles.nowrap)}>
                      {formatDateTime(d.finished_at)}
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
    </div>
  );
}
