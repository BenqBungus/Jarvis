import type { CompanionClient, SubmitTaskInput } from './client';
import type {
  CancelResponse,
  CapabilitiesResponse,
  StatusResponse,
  SubmitTaskResponse,
  TaskResource,
  TaskState,
} from '../contract/types';
import { CompanionApiError, CompanionNetworkError } from './errors';

/**
 * Deterministic, in-memory fixture adapter. No Math.random() anywhere in the
 * lifecycle timing or scenario selection, so Playwright/Vitest runs are
 * reproducible.
 *
 * Hard rule enforced by construction, not just convention: every piece of
 * text this adapter ever returns describes the *simulation itself*. It never
 * fabricates a system-telemetry-shaped value (a CPU/GPU temperature, a
 * plausible-looking "file deleted" success message, etc.) -- there is
 * nothing in this file capable of producing that, by design, so a future
 * edit that tries to add one should look obviously out of place.
 */
type Scenario = 'default' | 'approve' | 'fail' | 'flaky';

interface MockTaskEntry {
  resource: TaskResource;
  requestId: string;
  scenario: Scenario;
  flakyThrown: boolean;
  timers: ReturnType<typeof setTimeout>[];
}

const RUNNING_DELAY_MS = 600;
const RESOLUTION_DELAY_MS = 2500;
const CANCEL_DELAY_MS = 400;

function pickScenario(text: string): Scenario {
  const lowered = text.toLowerCase();
  if (lowered.includes('approve')) return 'approve';
  if (lowered.includes('fail')) return 'fail';
  if (lowered.includes('flaky')) return 'flaky';
  return 'default';
}

let mockTaskCounter = 0;
function nextMockTaskId(): string {
  mockTaskCounter += 1;
  return `mock-task-${mockTaskCounter}`;
}

function publicResource(entry: MockTaskEntry): TaskResource {
  // Shallow copy: callers must never be able to mutate our internal store
  // by mutating the object we handed them.
  return { ...entry.resource };
}

export class MockCompanionAdapter implements CompanionClient {
  readonly mode = 'mock' as const;

  private tasks = new Map<string, MockTaskEntry>();
  private activeTaskId: string | null = null;

  async getCapabilities(): Promise<CapabilitiesResponse> {
    // Matches the contract's own example exactly -- gating logic (push-to-
    // talk, image upload) is exercised against today's real contract, not a
    // hoped-for future one.
    return {
      version: '0.1',
      device_name: 'Jarvis PC (mock)',
      features: {
        text_tasks: true,
        task_cancel: true,
        voice: false,
        image_upload: false,
        remote_approval: false,
      },
    };
  }

  async getStatus(): Promise<StatusResponse> {
    return {
      online: true,
      state: this.activeTaskId ? 'busy' : 'idle',
      active_task_id: this.activeTaskId,
    };
  }

  async submitTask(input: SubmitTaskInput): Promise<SubmitTaskResponse> {
    const existing = [...this.tasks.values()].find((entry) => entry.requestId === input.requestId);
    if (existing) {
      // Idempotent resend: contract says request_id is "idempotent per
      // paired device" -- return the already-created task, don't spawn a
      // second one.
      return { task_id: existing.resource.task_id, state: existing.resource.state };
    }

    const taskId = nextMockTaskId();
    const scenario = pickScenario(input.text);
    const entry: MockTaskEntry = {
      requestId: input.requestId,
      scenario,
      flakyThrown: false,
      timers: [],
      resource: {
        task_id: taskId,
        state: 'queued',
        summary: 'Queued (mock).',
        result: null,
        error: null,
        revision: 1,
      },
    };
    this.tasks.set(taskId, entry);
    this.activeTaskId = taskId;
    this.scheduleLifecycle(entry);
    return { task_id: taskId, state: 'queued' };
  }

  async getTask(taskId: string): Promise<TaskResource> {
    const entry = this.tasks.get(taskId);
    if (!entry) {
      throw new CompanionApiError({
        code: 'not_found',
        message: 'Unknown task_id (mock adapter has no record of it).',
        retryable: false,
      });
    }
    if (entry.scenario === 'flaky' && !entry.flakyThrown) {
      entry.flakyThrown = true;
      throw new CompanionNetworkError('Simulated transient network failure (mock "flaky" scenario).');
    }
    return publicResource(entry);
  }

  async cancelTask(taskId: string): Promise<CancelResponse> {
    const entry = this.tasks.get(taskId);
    if (!entry) {
      throw new CompanionApiError({
        code: 'not_found',
        message: 'Unknown task_id (mock adapter has no record of it).',
        retryable: false,
      });
    }
    if (isTerminal(entry.resource.state)) {
      // Contract: "does not undo completed actions" -- cancelling a task
      // that already reached a terminal state is a no-op, not an error.
      return { task_id: taskId, cancel_requested: true };
    }
    clearEntryTimers(entry);
    // Cooperative, not instant: the task only actually flips to `cancelled`
    // on the next simulated tick, same as a real server would need time to
    // notice and stop work in flight.
    entry.timers.push(
      setTimeout(() => {
        if (isTerminal(entry.resource.state)) return; // lost the race to a real completion; leave it
        entry.resource = { ...entry.resource, state: 'cancelled', summary: 'Cancelled (mock).', revision: entry.resource.revision + 1 };
        if (this.activeTaskId === taskId) this.activeTaskId = null;
      }, CANCEL_DELAY_MS),
    );
    return { task_id: taskId, cancel_requested: true };
  }

  /** Test-only escape hatch: not part of CompanionClient, so UI code can
   * never accidentally depend on it. Clears every pending timer so Vitest
   * runs don't leak timers across test cases. */
  disposeForTests(): void {
    for (const entry of this.tasks.values()) clearEntryTimers(entry);
    this.tasks.clear();
    this.activeTaskId = null;
  }

  private scheduleLifecycle(entry: MockTaskEntry): void {
    entry.timers.push(
      setTimeout(() => {
        entry.resource = { ...entry.resource, state: 'running', summary: 'Running (mock).', revision: entry.resource.revision + 1 };
      }, RUNNING_DELAY_MS),
    );

    entry.timers.push(
      setTimeout(() => {
        switch (entry.scenario) {
          case 'approve':
            entry.resource = {
              ...entry.resource,
              state: 'awaiting_desktop_approval',
              summary: 'Waiting for desktop approval (mock). This state does not resolve on its own in mock mode.',
              revision: entry.resource.revision + 1,
            };
            break;
          case 'fail':
            entry.resource = {
              ...entry.resource,
              state: 'failed',
              summary: 'Failed (mock).',
              error: { code: 'mock_failure', message: 'Simulated failure (mock "fail" scenario). Nothing on your laptop was touched.', retryable: true },
              revision: entry.resource.revision + 1,
            };
            if (this.activeTaskId === entry.resource.task_id) this.activeTaskId = null;
            break;
          case 'default':
          case 'flaky':
          default:
            entry.resource = {
              ...entry.resource,
              state: 'completed',
              summary: 'Completed (mock).',
              result: 'Mock adapter finished simulating this task. This is fixture data, not a result from your laptop.',
              revision: entry.resource.revision + 1,
            };
            if (this.activeTaskId === entry.resource.task_id) this.activeTaskId = null;
            break;
        }
      }, RUNNING_DELAY_MS + RESOLUTION_DELAY_MS),
    );
  }
}

function isTerminal(state: TaskState): boolean {
  return state === 'completed' || state === 'failed' || state === 'cancelled';
}

function clearEntryTimers(entry: MockTaskEntry): void {
  for (const timer of entry.timers) clearTimeout(timer);
  entry.timers = [];
}
