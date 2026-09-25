import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';

import { useServiceOptions } from '../api/queries';
import { useCreateDeployment } from '../api/resources';
import { Button, Field, FormActions } from '../components/Form';
import { inputClass } from '../components/formStyles';
import { useToast } from '../components/toastContext';
import { fromLocalInput, nowLocalInput } from '../lib/datetime';
import { STATUS_LABELS } from '../lib/labels';
import {
  type DeploymentValues,
  deploymentSchema,
  ENVIRONMENTS,
  KINDS,
  STATUSES,
} from '../lib/schemas';
import { useMutationErrors } from '../lib/useMutationErrors';
import styles from './Pages.module.css';

const FIELDS = [
  'service_id',
  'environment',
  'kind',
  'release',
  'head_sha',
  'status',
  'started_at',
  'finished_at',
  'deployed_by',
  'pipeline_url',
] as const;

export function DeploymentNewPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const services = useServiceOptions();
  const create = useCreateDeployment();
  const now = nowLocalInput();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<DeploymentValues>({
    resolver: zodResolver(deploymentSchema),
    defaultValues: {
      service_id: '',
      environment: 'production',
      kind: 'planned',
      release: '',
      head_sha: '',
      status: 'succeeded',
      started_at: now,
      finished_at: now,
      deployed_by: '',
      pipeline_url: '',
    },
  });
  const onError = useMutationErrors<DeploymentValues>({ setError, fields: FIELDS });

  const onSubmit = handleSubmit(async (values) => {
    try {
      const deployment = await create.mutateAsync({
        service_id: values.service_id,
        environment: values.environment,
        kind: values.kind,
        release: values.release,
        head_sha: values.head_sha || null,
        status: values.status,
        started_at: fromLocalInput(values.started_at) ?? values.started_at,
        finished_at: fromLocalInput(values.finished_at),
        deployed_by: values.deployed_by || null,
        pipeline_url: values.pipeline_url || null,
      });
      toast.show({ tone: 'success', message: 'Deployment recorded.' });
      void navigate(`/deployments/${deployment.id}`);
    } catch (error) {
      onError(error);
    }
  });

  return (
    <div className={styles.page}>
      <h1>New deployment</h1>
      <form
        className={styles.panel}
        aria-label="New deployment"
        noValidate
        onSubmit={(event) => void onSubmit(event)}
      >
        <div className={styles.formGrid}>
          <Field label="Service" error={errors.service_id?.message}>
            {(props) => (
              <select {...props} {...register('service_id')} className={inputClass}>
                <option value="">Choose a service…</option>
                {services.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Environment" error={errors.environment?.message}>
            {(props) => (
              <select {...props} {...register('environment')} className={inputClass}>
                {ENVIRONMENTS.map((env) => (
                  <option key={env} value={env}>
                    {env}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Kind" error={errors.kind?.message}>
            {(props) => (
              <select {...props} {...register('kind')} className={inputClass}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k === 'planned' ? 'Planned' : 'Remediation (unplanned fix)'}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Release" error={errors.release?.message}>
            {(props) => <input {...props} {...register('release')} className={inputClass} />}
          </Field>
          <Field label="Head commit SHA" error={errors.head_sha?.message}>
            {(props) => <input {...props} {...register('head_sha')} className={inputClass} />}
          </Field>
          <Field label="Status" error={errors.status?.message}>
            {(props) => (
              <select {...props} {...register('status')} className={inputClass}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABELS[s]}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Started at" error={errors.started_at?.message}>
            {(props) => (
              <input
                {...props}
                {...register('started_at')}
                type="datetime-local"
                className={inputClass}
              />
            )}
          </Field>
          <Field
            label="Finished at"
            hint="Required unless in progress."
            error={errors.finished_at?.message}
          >
            {(props) => (
              <input
                {...props}
                {...register('finished_at')}
                type="datetime-local"
                className={inputClass}
              />
            )}
          </Field>
          <Field label="Deployed by" error={errors.deployed_by?.message}>
            {(props) => <input {...props} {...register('deployed_by')} className={inputClass} />}
          </Field>
          <Field label="Pipeline URL" error={errors.pipeline_url?.message}>
            {(props) => (
              <input {...props} {...register('pipeline_url')} type="url" className={inputClass} />
            )}
          </Field>
        </div>
        <FormActions>
          <Button type="submit" disabled={isSubmitting}>
            Record deployment
          </Button>
        </FormActions>
      </form>
    </div>
  );
}
