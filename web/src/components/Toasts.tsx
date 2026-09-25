/**
 * Transient notifications. Errors that aren't tied to a form field show here
 * with the request ID, so a user can quote it in a report (§8).
 */
import { type ReactNode, useCallback, useMemo, useState } from 'react';

import { cx } from '../lib/cx';
import { type Toast, ToastContext } from './toastContext';
import styles from './Toasts.module.css';

const DISMISS_AFTER_MS = 8000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (toast: Omit<Toast, 'id'>) => {
      const id = Date.now() + Math.random();
      setToasts((current) => [...current, { ...toast, id }]);
      window.setTimeout(() => {
        dismiss(id);
      }, DISMISS_AFTER_MS);
    },
    [dismiss],
  );

  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.region} aria-live="polite" aria-label="Notifications">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cx(styles.toast, styles[toast.tone])}
            role={toast.tone === 'error' ? 'alert' : 'status'}
          >
            <p className={styles.message}>{toast.message}</p>
            {toast.requestId && (
              <p className={styles.meta}>
                Request ID: <code>{toast.requestId}</code>
              </p>
            )}
            <button
              type="button"
              className={styles.close}
              aria-label="Dismiss notification"
              onClick={() => {
                dismiss(toast.id);
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
