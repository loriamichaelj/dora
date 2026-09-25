import styles from './Pagination.module.css';

interface Props {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}

export function Pagination({ total, limit, offset, onChange }: Props) {
  if (total <= limit && offset === 0) return null;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <nav className={styles.pagination} aria-label="Pagination">
      <span>
        {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}
      </span>
      <button
        type="button"
        disabled={offset === 0}
        onClick={() => {
          onChange(Math.max(0, offset - limit));
        }}
      >
        Previous
      </button>
      <button
        type="button"
        disabled={offset + limit >= total}
        onClick={() => {
          onChange(offset + limit);
        }}
      >
        Next
      </button>
    </nav>
  );
}
