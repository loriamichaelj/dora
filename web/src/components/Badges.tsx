/** Status, kind, and severity badges: always text, color is only a cue (§8). */
import type { Schemas } from '../api/client';
import { cx } from '../lib/cx';
import { STATUS_LABELS } from '../lib/labels';
import styles from './Badges.module.css';

type Status = Schemas['DeploymentOut']['status'];
type Kind = Schemas['DeploymentOut']['kind'];
type Severity = Schemas['FailureOut']['severity'];

const STATUS_TONE: Record<Status, string | undefined> = {
  in_progress: styles.info,
  succeeded: styles.good,
  failed: styles.bad,
  rolled_back: styles.warn,
};

export function StatusBadge({ status }: { status: Status }) {
  return <span className={cx(styles.badge, STATUS_TONE[status])}>{STATUS_LABELS[status]}</span>;
}

export function KindBadge({ kind }: { kind: Kind }) {
  return kind === 'remediation' ? (
    <span className={cx(styles.badge, styles.warn)}>Remediation</span>
  ) : (
    <span className={cx(styles.badge, styles.neutral)}>Planned</span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const tone =
    severity === 'sev1' ? styles.bad : severity === 'sev2' ? styles.warn : styles.neutral;
  return <span className={cx(styles.badge, tone)}>{severity.toUpperCase()}</span>;
}

export function OpenBadge({ resolvedAt }: { resolvedAt: string | null }) {
  return resolvedAt ? (
    <span className={cx(styles.badge, styles.good)}>Resolved</span>
  ) : (
    <span className={cx(styles.badge, styles.bad)}>Open</span>
  );
}
