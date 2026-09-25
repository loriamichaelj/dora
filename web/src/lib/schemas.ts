/**
 * Client-side form validation. It mirrors the API's rules for fast feedback,
 * but the API stays the source of truth: its field errors are shown inline too.
 */
import { z } from 'zod';

import { fromLocalInput } from './datetime';

const serviceFields = {
  name: z.string().trim().min(1, 'Required.').max(200, 'At most 200 characters.'),
  owner_team: z.string().trim().min(1, 'Required.').max(100, 'At most 100 characters.'),
  repo_url: z.string().trim().max(2048, 'At most 2048 characters.'),
};

export const createServiceSchema = z.object({
  slug: z
    .string()
    .regex(
      /^[a-z0-9][a-z0-9-]{1,62}$/,
      'Use 2–63 lowercase letters, digits, or hyphens, starting with a letter or digit.',
    ),
  ...serviceFields,
});
export type CreateServiceValues = z.infer<typeof createServiceSchema>;

export const editServiceSchema = z.object(serviceFields);
export type EditServiceValues = z.infer<typeof editServiceSchema>;

export const ENVIRONMENTS = ['production', 'staging', 'development'] as const;
export const STATUSES = ['in_progress', 'succeeded', 'failed', 'rolled_back'] as const;
export const KINDS = ['planned', 'remediation'] as const;
export const SEVERITIES = ['sev1', 'sev2', 'sev3', 'sev4'] as const;

export const deploymentSchema = z
  .object({
    service_id: z.string().min(1, 'Choose a service.'),
    environment: z.enum(ENVIRONMENTS),
    kind: z.enum(KINDS),
    release: z.string().trim().min(1, 'Required.').max(100, 'At most 100 characters.'),
    head_sha: z
      .string()
      .trim()
      .regex(/^([0-9a-fA-F]{7,40})?$/, 'Use 7–40 hexadecimal characters.'),
    status: z.enum(STATUSES),
    started_at: z.string().min(1, 'Required.'),
    finished_at: z.string(),
    deployed_by: z.string().trim().max(200, 'At most 200 characters.'),
    pipeline_url: z.string().trim().max(2048, 'At most 2048 characters.'),
  })
  .superRefine((values, ctx) => {
    const started = fromLocalInput(values.started_at);
    const finished = fromLocalInput(values.finished_at);
    if (values.status === 'in_progress' && values.finished_at) {
      ctx.addIssue({
        code: 'custom',
        path: ['finished_at'],
        message: 'Leave empty while the deployment is in progress.',
      });
    }
    if (values.status !== 'in_progress' && !values.finished_at) {
      ctx.addIssue({ code: 'custom', path: ['finished_at'], message: 'Required for this status.' });
    }
    if (started && finished && finished < started) {
      ctx.addIssue({
        code: 'custom',
        path: ['finished_at'],
        message: 'Must be at or after the start time.',
      });
    }
  });
export type DeploymentValues = z.infer<typeof deploymentSchema>;

export const failureSchema = z
  .object({
    severity: z.enum(SEVERITIES),
    summary: z.string().trim().min(1, 'Required.').max(500, 'At most 500 characters.'),
    detected_at: z.string().min(1, 'Required.'),
    resolved_at: z.string(),
  })
  .superRefine((values, ctx) => {
    const detected = fromLocalInput(values.detected_at);
    const resolved = fromLocalInput(values.resolved_at);
    if (detected && resolved && resolved < detected) {
      ctx.addIssue({
        code: 'custom',
        path: ['resolved_at'],
        message: 'Must be at or after the detection time.',
      });
    }
  });
export type FailureValues = z.infer<typeof failureSchema>;

export const resolveSchema = z.object({ resolved_at: z.string().min(1, 'Required.') });
export type ResolveValues = z.infer<typeof resolveSchema>;
