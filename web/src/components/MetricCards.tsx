import type { Schemas } from '../api/client';
import { formatFrequency, formatHours, formatPercent, plural } from '../lib/format';
import { MetricCard } from './MetricCard';
import styles from './MetricCards.module.css';

/** The five DORA metrics, grouped as throughput and instability (§8). */
export function MetricCards({ summary }: { summary: Schemas['DoraSummary'] }) {
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
