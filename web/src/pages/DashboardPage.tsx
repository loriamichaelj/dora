import { useSearchParams } from 'react-router';

import type { Schemas } from '../api/client';
import { useDoraSummary, useDoraTimeseries, useServiceOptions } from '../api/queries';
import { MetricCard } from '../components/MetricCard';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { TrendChart } from '../components/TrendChart';
import {
  formatAxisHours,
  formatAxisPercent,
  formatFrequency,
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
        <h1>DORA metrics</h1>
        <p className={styles.subtitle}>
          Software delivery performance for {filters.environment}
          {summary.data?.window && `, ${plural(Math.round(summary.data.window.days), 'day')}`}.
        </p>
      </header>

      <form
        className={styles.filters}
        aria-label="Filters"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <label>
          Service
          <select
            value={filters.serviceId ?? ''}
            onChange={(e) => {
              update({ serviceId: e.target.value || null });
            }}
          >
            <option value="">All services</option>
            {services.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Environment
          <select
            value={filters.environment}
            onChange={(e) => {
              update({ environment: e.target.value as DashboardFilters['environment'] });
            }}
          >
            {ENVIRONMENTS.map((env) => (
              <option key={env} value={env}>
                {env}
              </option>
            ))}
          </select>
        </label>
        <label>
          Window
          <select
            value={filters.preset}
            onChange={(e) => {
              update({ preset: e.target.value as DashboardFilters['preset'] });
            }}
          >
            {PRESETS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        {filters.preset === 'custom' && (
          <>
            <label>
              From
              <input
                type="date"
                value={filters.from}
                onChange={(e) => {
                  update({ from: e.target.value });
                }}
              />
            </label>
            <label>
              To
              <input
                type="date"
                value={filters.to}
                onChange={(e) => {
                  update({ to: e.target.value });
                }}
              />
            </label>
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

function MetricCards({ summary }: { summary: Schemas['DoraSummary'] }) {
  const f = summary.deployment_frequency;
  const lt = summary.change_lead_time;
  const cfr = summary.change_fail_rate;
  const rec = summary.failed_deployment_recovery_time;
  const rw = summary.deployment_rework_rate;
  const days = Math.round(summary.window.days);
  const excluded = lt.excluded_samples
    ? ` · ${String(lt.excluded_samples)} excluded (clock skew)`
    : '';

  return (
    <>
      <section aria-labelledby="throughput" className={styles.section}>
        <h2 id="throughput">Throughput</h2>
        <div className={styles.grid}>
          <MetricCard
            title="Deployment frequency"
            value={formatFrequency(f.per_day)}
            band={f.band}
            detail={`${plural(f.count, 'deployment')} · ${String(f.deploy_days)} of ${plural(days, 'day')} had one`}
            definition="Successful deployments to this environment."
          />
          <MetricCard
            title="Change lead time"
            value={formatHours(lt.median_hours)}
            band={lt.band}
            detail={`p90 ${formatHours(lt.p90_hours)} · ${plural(lt.sample_size, 'commit')}${excluded}`}
            definition="Median time from commit to its first live deployment."
          />
          <MetricCard
            title="Failed deployment recovery time"
            value={formatHours(rec.median_hours)}
            band={rec.band}
            detail={`${plural(rec.sample_size, 'resolved failure')} · ${String(rec.open_failures)} open`}
            definition="Median time from detecting a failure to resolving it."
          />
        </div>
      </section>
      <section aria-labelledby="instability" className={styles.section}>
        <h2 id="instability">Instability</h2>
        <div className={styles.grid}>
          <MetricCard
            title="Change fail rate"
            value={formatPercent(cfr.rate)}
            band={cfr.band}
            detail={`${String(cfr.failed_deployments)} of ${plural(cfr.total_deployments, 'deployment')} caused a failure`}
            definition="Share of deployments that caused a production failure."
          />
          <MetricCard
            title="Deployment rework rate"
            value={formatPercent(rw.rate)}
            band={rw.band}
            bandEmptyLabel="No published benchmark"
            detail={`${String(rw.remediation_deployments)} of ${plural(rw.total_deployments, 'deployment')} were remediation`}
            definition="Share of deployments that were unplanned fixes."
          />
        </div>
      </section>
    </>
  );
}

function Trends({ points }: { points: Schemas['TimeseriesPoint'][] }) {
  return (
    <div className={styles.charts}>
      <TrendChart
        title="Deployments per week"
        kind="bar"
        points={points}
        series={[{ key: 'deployment_count', label: 'Deployments', color: '#2456c4' }]}
        format={(v) => String(Math.round(v))}
      />
      <TrendChart
        title="Median change lead time"
        kind="line"
        points={points}
        series={[{ key: 'median_lead_time_hours', label: 'Lead time', color: '#146c3c' }]}
        format={formatHours}
        axisFormat={formatAxisHours}
      />
      <TrendChart
        title="Change fail and rework rates"
        kind="line"
        points={points}
        series={[
          { key: 'change_fail_rate', label: 'Change fail rate', color: '#b42318' },
          { key: 'rework_rate', label: 'Rework rate', color: '#845400' },
        ]}
        format={formatPercent}
        axisFormat={formatAxisPercent}
      />
      <TrendChart
        title="Median recovery time"
        kind="line"
        points={points}
        series={[{ key: 'median_recovery_hours', label: 'Recovery time', color: '#6941c6' }]}
        format={formatHours}
        axisFormat={formatAxisHours}
      />
    </div>
  );
}
