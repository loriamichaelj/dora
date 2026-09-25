/** Loading, empty, and error states shared by every data view (§8). */
import type { ReactNode } from 'react';

import { ApiError } from '../api/client';
import { cx } from '../lib/cx';
import styles from './States.module.css';

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      {label}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={styles.state}>
      <p className={styles.title}>{title}</p>
      {children}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.';
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div className={cx(styles.state, styles.error)} role="alert">
      <p className={styles.title}>Couldn’t load this data</p>
      <p>{message}</p>
      {requestId && (
        <p className={styles.meta}>
          Request ID: <code>{requestId}</code>
        </p>
      )}
      {onRetry && (
        <button type="button" className={styles.retry} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
