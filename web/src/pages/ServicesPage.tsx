import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate, useSearchParams } from 'react-router';

import { PAGE_SIZE, useCreateService, useServicesPage } from '../api/resources';
import { Button, Field, FormActions } from '../components/Form';
import { Icon } from '../components/Icon';
import { inputClass } from '../components/formStyles';
import { Pagination } from '../components/Pagination';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { useToast } from '../components/toastContext';
import { cx } from '../lib/cx';
import { formatDateTime } from '../lib/format';
import { type CreateServiceValues, createServiceSchema } from '../lib/schemas';
import { useMutationErrors } from '../lib/useMutationErrors';
import styles from './Pages.module.css';

const CREATE_FIELDS = ['slug', 'name', 'owner_team', 'repo_url'] as const;

export function ServicesPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const offset = Number(params.get('offset') ?? 0) || 0;
  const [creating, setCreating] = useState(false);
  const page = useServicesPage({ q, offset });

  const setQuery = (next: { q?: string; offset?: number }) => {
    const merged = new URLSearchParams();
    const nextQ = next.q ?? q;
    const nextOffset = next.offset ?? 0;
    if (nextQ) merged.set('q', nextQ);
    if (nextOffset) merged.set('offset', String(nextOffset));
    setParams(merged, { replace: true });
  };

  return (
    <div className={styles.page}>
      <div className={styles.titleRow}>
        <div>
          <h1>Services</h1>
          <p className={styles.subtitle}>Everything that ships, and the team that owns it.</p>
        </div>
        <Button
          variant={creating ? 'secondary' : 'primary'}
          onClick={() => {
            setCreating((open) => !open);
          }}
          aria-expanded={creating}
        >
          {creating ? (
            'Cancel'
          ) : (
            <>
              <Icon name="plus" />
              New service
            </>
          )}
        </Button>
      </div>

      {creating && (
        <CreateServiceForm
          onDone={() => {
            setCreating(false);
          }}
        />
      )}

      <form
        className={styles.toolbar}
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          const value = new FormData(event.currentTarget).get('q');
          setQuery({ q: typeof value === 'string' ? value.trim() : '' });
        }}
      >
        <Field label="Search by name or slug" className={styles.grow}>
          {(props) => <input {...props} name="q" defaultValue={q} className={inputClass} />}
        </Field>
        <div className={styles.fit}>
          <Button type="submit" variant="secondary">
            <Icon name="search" />
            Search
          </Button>
        </div>
      </form>

      {page.isPending ? (
        <LoadingState label="Loading services…" />
      ) : page.isError ? (
        <ErrorState error={page.error} onRetry={() => void page.refetch()} />
      ) : page.data.items.length === 0 ? (
        <EmptyState title={q ? `No services match “${q}”` : 'No services yet'}>
          <p>{q ? 'Try a different search.' : 'Create one to start recording deployments.'}</p>
        </EmptyState>
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Slug</th>
                  <th scope="col">Owner team</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {page.data.items.map((service) => (
                  <tr key={service.id}>
                    <td className={styles.primaryCell}>
                      <Link to={`/services/${service.id}`}>{service.name}</Link>
                    </td>
                    <td className={styles.mono}>{service.slug}</td>
                    <td>{service.owner_team}</td>
                    <td className={cx(styles.muted, styles.nowrap)}>
                      {formatDateTime(service.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            total={page.data.total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={(next) => {
              setQuery({ offset: next });
            }}
          />
        </>
      )}
    </div>
  );
}

function CreateServiceForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const create = useCreateService();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CreateServiceValues>({
    resolver: zodResolver(createServiceSchema),
    defaultValues: { slug: '', name: '', owner_team: '', repo_url: '' },
  });
  const onError = useMutationErrors<CreateServiceValues>({ setError, fields: CREATE_FIELDS });

  const onSubmit = handleSubmit(async (values) => {
    try {
      const service = await create.mutateAsync({ ...values, repo_url: values.repo_url || null });
      toast.show({ tone: 'success', message: `Created ${service.name}.` });
      onDone();
      void navigate(`/services/${service.id}`);
    } catch (error) {
      onError(error);
    }
  });

  return (
    <form
      className={styles.panel}
      aria-label="New service"
      noValidate
      onSubmit={(event) => void onSubmit(event)}
    >
      <h2>New service</h2>
      <div className={styles.formGrid}>
        <Field label="Slug" error={errors.slug?.message} hint="Permanent: used by pipelines.">
          {(props) => <input {...props} {...register('slug')} className={inputClass} />}
        </Field>
        <Field label="Name" error={errors.name?.message}>
          {(props) => <input {...props} {...register('name')} className={inputClass} />}
        </Field>
        <Field label="Owner team" error={errors.owner_team?.message}>
          {(props) => <input {...props} {...register('owner_team')} className={inputClass} />}
        </Field>
        <Field label="Repository URL" error={errors.repo_url?.message}>
          {(props) => (
            <input {...props} {...register('repo_url')} type="url" className={inputClass} />
          )}
        </Field>
      </div>
      <FormActions>
        <Button type="submit" disabled={isSubmitting}>
          Create service
        </Button>
      </FormActions>
    </form>
  );
}
