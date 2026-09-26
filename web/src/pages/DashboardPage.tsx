import { useSearchParams } from 'react-router';

import type { Schemas } from '../api/client';
import { useDoraSummary, useDoraTimeseries, useServiceOptions } from '../api/queries';
import { Field } from '../components/Form';
import { inputClass } from '../components/formStyles';
import { MetricCards } from '../components/MetricCards';
import { SegmentedControl } from '../components/SegmentedControl';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { TrendChart } from '../components/TrendChart';
import {
  formatAxisHours,
  formatAxisPercent,
  formatHours,
  formatPercent,
  plural,
} from '../lib/format';
import {
  type DashboardFilters,
  ENVIRONMENTS,
  PRESETS,
  readFilters,
  resolveWindow,
  writeFilters,
} from '../lib/window';
import styles from './DashboardPage.module.css';

export const DISCLAIMER = 'Benchmarks are for team self-improvement, not cross-team comparison.';

export function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const resolved = resolveWindow(filters);
  const query =
    'window' in resolved
      ? { serviceId: filters.serviceId, environment: filters.environment, window: resolved.window }
      : null;

  const services = useServiceOptions();
  const summary = useDoraSummary(query);
  const series = useDoraTimeseries(query);

  const update = (patch: Partial<DashboardFilters>) => {
    setParams(writeFilters({ ...filters, ...patch }), { replace: true });
  };

  return (
    <div className={styles.page}>
      <header className={styles.heading}>
        <div>
          <h1>DORA metrics</h1>
          <p className={styles.subtitle}>
            Software delivery performance for {filters.environment}
            {summary.data?.window && `, ${plural(Math.round(summary.data.window.days), 'day')}`}.
          </p>
        </div>
        <SegmentedControl
          label="Window"
          value={filters.preset}
          options={PRESETS.map((p) => ({ value: p.value, label: p.short, title: p.label }))}
          onChange={(preset) => {
            update({ preset });
          }}
        />
      </header>

      <form
        className={styles.filters}
        aria-label="Filters"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <Field label="Service">
          {(props) => (
            <select
              {...props}
              value={filters.serviceId ?? ''}
              onChange={(e) => {
                update({ serviceId: e.target.value || null });
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
        <Field label="Environment">
          {(props) => (
            <select
              {...props}
              value={filters.environment}
              onChange={(e) => {
                update({ environment: e.target.value as DashboardFilters['environment'] });
              }}
              className={inputClass}
            >
              {ENVIRONMENTS.map((env) => (
                <option key={env} value={env}>
                  {env}
                </option>
              ))}
            </select>
          )}
        </Field>
        {filters.preset === 'custom' && (
          <>
            <Field label="From">
              {(props) => (
                <input
                  {...props}
                  type="date"
                  value={filters.from}
                  onChange={(e) => {
                    update({ from: e.target.value });
                  }}
                  className={inputClass}
                />
              )}
            </Field>
            <Field label="To">
              {(props) => (
                <input
                  {...props}
                  type="date"
                  value={filters.to}
                  onChange={(e) => {
                    update({ to: e.target.value });
                  }}
                  className={inputClass}
                />
              )}
            </Field>
          </>
        )}
      </form>

      {'error' in resolved ? (
        <p className={styles.formError} role="alert">
          {resolved.error}
        </p>
      ) : summary.isPending ? (
        <LoadingState label="Loading metrics…" />
      ) : summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : summary.data.deployment_frequency.count === 0 ? (
        <EmptyState title="No deployments in this window">
          <p>
            Nothing was deployed to {filters.environment} in this period. Try a longer window,
            another environment, or another service.
          </p>
        </EmptyState>
      ) : (
        <>
          <MetricCards summary={summary.data} />
          <section aria-labelledby="trends" className={styles.section}>
            <h2 id="trends">Weekly trends</h2>
            {series.isPending ? (
              <LoadingState label="Loading trends…" />
            ) : series.isError ? (
              <ErrorState error={series.error} onRetry={() => void series.refetch()} />
            ) : (
              <Trends points={series.data.points} />
            )}
          </section>
        </>
      )}

      <p className={styles.disclaimer}>
        {DISCLAIMER} Bands: <code>{summary.data?.band_set ?? 'dora-2023-adapted'}</code>.
      </p>
    </div>
  );
}

function Trends({ points }: { points: Schemas['TimeseriesPoint'][] }) {
  return (
    <div className={styles.charts}>
      <TrendChart
        title="Deployments per week"
        kind="bar"
        points={points}
        series={[{ key: 'deployment_count', label: 'Deployments', color: 'var(--chart-2)' }]}
        format={(v) => String(Math.round(v))}
      />
      <TrendChart
        title="Median change lead time"
        kind="line"
        points={points}
        series={[{ key: 'median_lead_time_hours', label: 'Lead time', color: 'var(--chart-3)' }]}
        format={formatHours}
        axisFormat={formatAxisHours}
      />
      <TrendChart
        title="Change fail and rework rates"
        kind="line"
        points={points}
        series={[
          { key: 'change_fail_rate', label: 'Change fail rate', color: 'var(--chart-3)' },
          { key: 'rework_rate', label: 'Rework rate', color: 'var(--chart-2)', dashed: true },
        ]}
        format={formatPercent}
        axisFormat={formatAxisPercent}
      />
      <TrendChart
        title="Median recovery time"
        kind="line"
        points={points}
        series={[{ key: 'median_recovery_hours', label: 'Recovery time', color: 'var(--chart-3)' }]}
        format={formatHours}
        axisFormat={formatAxisHours}
      />
    </div>
  );
}
