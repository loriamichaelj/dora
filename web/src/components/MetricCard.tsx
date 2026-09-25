import { type Band, BandBadge } from './BandBadge';
import styles from './MetricCard.module.css';

interface Props {
  title: string;
  value: string;
  band: Band | null | undefined;
  /** Sample size and context, e.g. "2 of 4 deployments". */
  detail: string;
  definition: string;
  bandEmptyLabel?: string;
}

export function MetricCard({ title, value, band, detail, definition, bandEmptyLabel }: Props) {
  return (
    <article className={styles.card} aria-label={title}>
      <header className={styles.header}>
        <h3 className={styles.title}>{title}</h3>
        <BandBadge band={band} {...(bandEmptyLabel ? { emptyLabel: bandEmptyLabel } : {})} />
      </header>
      <p className={styles.value}>{value}</p>
      <p className={styles.detail}>{detail}</p>
      <p className={styles.definition}>{definition}</p>
    </article>
  );
}
