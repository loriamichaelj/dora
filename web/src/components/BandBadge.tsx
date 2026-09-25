import type { Schemas } from '../api/client';
import { cx } from '../lib/cx';
import styles from './BandBadge.module.css';

export type Band = NonNullable<Schemas['DeploymentFrequency']['band']>;

const LABELS: Record<Band, string> = {
  elite: 'Elite',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

interface Props {
  band: Band | null | undefined;
  /** Shown when there's no band, e.g. "No published benchmark". */
  emptyLabel?: string;
}

/** A band is always spelled out in text; the color is only a secondary cue. */
export function BandBadge({ band, emptyLabel = 'No band' }: Props) {
  if (!band) {
    return <span className={cx(styles.badge, styles.none)}>{emptyLabel}</span>;
  }
  return (
    <span className={cx(styles.badge, styles[band])}>
      <span className="visually-hidden">Benchmark band: </span>
      {LABELS[band]}
    </span>
  );
}
