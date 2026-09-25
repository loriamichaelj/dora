import type { Schemas } from '../api/client';

type Status = Schemas['DeploymentOut']['status'];

export const STATUS_LABELS: Record<Status, string> = {
  in_progress: 'In progress',
  succeeded: 'Succeeded',
  failed: 'Failed',
  rolled_back: 'Rolled back',
};
