/**
 * One policy for write errors (§8):
 * - 412: someone else changed the record. Say so, and the caller refetches.
 * - field errors: shown inline on the matching inputs.
 * - anything else: a toast with the request ID.
 */
import { useCallback } from 'react';
import type { FieldValues, Path, UseFormSetError } from 'react-hook-form';

import { ApiError } from '../api/client';
import { useToast } from '../components/toastContext';

export const EDIT_CONFLICT_MESSAGE =
  'This record was changed by someone else. The latest version has been loaded; review it and try again.';

export function useMutationErrors<T extends FieldValues>(options: {
  setError?: UseFormSetError<T>;
  fields?: readonly Path<T>[];
  onConflict?: () => void;
}) {
  const toast = useToast();
  const { setError, fields, onConflict } = options;

  return useCallback(
    (error: unknown) => {
      if (!(error instanceof ApiError)) {
        toast.show({ tone: 'error', message: 'Something went wrong.' });
        return;
      }
      if (error.isEditConflict) {
        toast.show({ tone: 'error', message: EDIT_CONFLICT_MESSAGE, requestId: error.requestId });
        onConflict?.();
        return;
      }
      const inline = Object.entries(error.fieldErrors).filter(([field]) =>
        (fields as readonly string[] | undefined)?.includes(field),
      );
      if (setError && inline.length > 0) {
        for (const [field, message] of inline) {
          setError(field as Path<T>, { type: 'server', message });
        }
        return;
      }
      toast.show({ tone: 'error', message: error.message, requestId: error.requestId });
    },
    [toast, setError, fields, onConflict],
  );
}
