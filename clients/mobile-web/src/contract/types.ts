/**
 * Hand-mirrored from contracts/companion-v1.json (read-only; owned by
 * Codex). Field names match the JSON exactly so a future contract diff is a
 * diff against this one file. Do not add fields the contract doesn't have --
 * see clients/CONTRACT_REQUESTS.md for the gaps this client actually found.
 */

export type TaskState =
  | 'queued'
  | 'running'
  | 'awaiting_desktop_approval'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface CapabilitiesFeatures {
  text_tasks: boolean;
  task_cancel: boolean;
  voice: boolean;
  image_upload: boolean;
  remote_approval: boolean;
}

export interface CapabilitiesResponse {
  version: string;
  device_name: string;
  features: CapabilitiesFeatures;
}

export interface StatusResponse {
  online: boolean;
  state: string;
  active_task_id: string | null;
}

export interface SubmitTaskRequest {
  request_id: string;
  text: string;
  project_id: string | null;
}

export interface SubmitTaskResponse {
  task_id: string;
  state: TaskState;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
}

export interface TaskResource {
  task_id: string;
  state: TaskState;
  summary: string | null;
  result: unknown | null;
  error: ApiErrorBody | null;
  revision: number;
}

export interface CancelResponse {
  task_id: string;
  cancel_requested: boolean;
}

/** The contract's own stated text limit for POST /v1/tasks. */
export const TASK_TEXT_MAX_CHARACTERS = 3000;

/** States in which a task is still active and should keep being polled. */
export const NON_TERMINAL_TASK_STATES: readonly TaskState[] = [
  'queued',
  'running',
  'awaiting_desktop_approval',
];

export function isTerminalTaskState(state: TaskState): boolean {
  return !NON_TERMINAL_TASK_STATES.includes(state);
}
