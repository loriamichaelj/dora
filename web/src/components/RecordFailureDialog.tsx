import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';

import { useCreateFailure } from '../api/resources';
import { fromLocalInput, nowLocalInput } from '../lib/datetime';
import { type FailureValues, failureSchema, SEVERITIES } from '../lib/schemas';
import { useMutationErrors } from '../lib/useMutationErrors';
import { Dialog } from './Dialog';
import { Button, Field, FormActions } from './Form';
import { inputClass } from './formStyles';
import { useToast } from './toastContext';

const FIELDS = ['severity', 'summary', 'detected_at', 'resolved_at'] as const;

interface Props {
  open: boolean;
  deploymentId: string;
  /** Shown after a rollback: rolling back never records a failure by itself (§3, D4). */
  afterRollback?: boolean;
  onClose: () => void;
}

export function RecordFailureDialog({ open, deploymentId, afterRollback = false, onClose }: Props) {
  return (
    <Dialog
      open={open}
      title={afterRollback ? 'Record a failure for this rollback?' : 'Record failure'}
      onClose={onClose}
    >
      <RecordFailureForm
        deploymentId={deploymentId}
        afterRollback={afterRollback}
        onClose={onClose}
      />
    </Dialog>
  );
}

function RecordFailureForm({
  deploymentId,
  afterRollback,
  onClose,
}: Omit<Props, 'open'> & { afterRollback: boolean }) {
  const toast = useToast();
  const create = useCreateFailure();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FailureValues>({
    resolver: zodResolver(failureSchema),
    defaultValues: { severity: 'sev2', summary: '', detected_at: nowLocalInput(), resolved_at: '' },
  });
  const onError = useMutationErrors<FailureValues>({ setError, fields: FIELDS });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await create.mutateAsync({
        deployment_id: deploymentId,
        severity: values.severity,
        summary: values.summary,
        detected_at: fromLocalInput(values.detected_at) ?? values.detected_at,
        resolved_at: fromLocalInput(values.resolved_at),
      });
      toast.show({ tone: 'success', message: 'Failure recorded.' });
      onClose();
    } catch (error) {
      onError(error);
    }
  });

  return (
    <form aria-label="Record failure" noValidate onSubmit={(event) => void onSubmit(event)}>
      {afterRollback && (
        <p>
          A rollback doesn’t count as a failure on its own. If this deployment caused a production
          problem, record it so the change fail rate reflects it.
        </p>
      )}
      <Field label="Severity" error={errors.severity?.message}>
        {(props) => (
          <select {...props} {...register('severity')} className={inputClass}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s.toUpperCase()}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label="Summary" error={errors.summary?.message}>
        {(props) => <input {...props} {...register('summary')} className={inputClass} />}
      </Field>
      <Field label="Detected at" error={errors.detected_at?.message}>
        {(props) => (
          <input
            {...props}
            {...register('detected_at')}
            type="datetime-local"
            className={inputClass}
          />
        )}
      </Field>
      <Field
        label="Resolved at"
        hint="Leave empty if it's still open."
        error={errors.resolved_at?.message}
      >
        {(props) => (
          <input
            {...props}
            {...register('resolved_at')}
            type="datetime-local"
            className={inputClass}
          />
        )}
      </Field>
      <FormActions>
        <Button type="submit" disabled={isSubmitting}>
          Record failure
        </Button>
        <Button variant="secondary" onClick={onClose}>
          {afterRollback ? 'Not now' : 'Cancel'}
        </Button>
      </FormActions>
    </form>
  );
}
