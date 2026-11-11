import type {
  CancelResponse,
  CapabilitiesResponse,
  StatusResponse,
  SubmitTaskResponse,
  TaskResource,
} from '../contract/types';

export type ClientMode = 'mock' | 'transport';

export interface SubmitTaskInput {
  requestId: string;
  text: string;
  projectId?: string | null;
}

/**
 * The one shared shape both the mock adapter and the real transport adapter
 * implement. UI code is written against this interface only -- it never
 * imports either adapter directly except at the single selection point
 * (select-adapter.ts), so swapping mock for a real server later touches one
 * file, not the app.
 */
export interface CompanionClient {
  readonly mode: ClientMode;
  getCapabilities(signal?: AbortSignal): Promise<CapabilitiesResponse>;
  getStatus(signal?: AbortSignal): Promise<StatusResponse>;
  submitTask(input: SubmitTaskInput, signal?: AbortSignal): Promise<SubmitTaskResponse>;
  getTask(taskId: string, signal?: AbortSignal): Promise<TaskResource>;
  cancelTask(taskId: string, signal?: AbortSignal): Promise<CancelResponse>;
}
