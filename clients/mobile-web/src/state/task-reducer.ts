import type { ApiErrorBody, TaskState } from '../contract/types';
import { isTerminalTaskState } from '../contract/types';

export type TaskUiState =
  | { phase: 'idle' }
  | { phase: 'submitting'; requestId: string; text: string }
  | { phase: 'submit_failed'; requestId: string; text: string; message: string }
  | {
      phase: 'active';
      requestId: string | null; // null when attached via reconnect-on-load, not a fresh submit
      taskId: string;
      /** The text that was actually submitted, carried forward from
       * 'submitting' for the conversation log; null when attached via
       * reconnect-on-load, since a fresh page load never saw the original
       * request. */
      text: string | null;
      state: TaskState;
      summary: string | null;
      result: unknown | null;
      error: ApiErrorBody | null;
      revision: number;
      unchangedStreak: number;
      cancelRequested: boolean;
      pollError: string | null; // transient poll failure; last-known-good fields above are kept
    };

export type TaskAction =
  | { type: 'submit_started'; requestId: string; text: string }
  | { type: 'submit_succeeded'; taskId: string; state: TaskState }
  | { type: 'submit_failed'; message: string }
  | { type: 'attach_existing'; taskId: string }
  | { type: 'poll_succeeded'; taskId: string; state: TaskState; summary: string | null; result: unknown | null; error: ApiErrorBody | null; revision: number }
  | { type: 'poll_failed'; taskId: string; message: string }
  | { type: 'cancel_requested' }
  | { type: 'dismiss' };

export const initialTaskState: TaskUiState = { phase: 'idle' };

export function taskReducer(state: TaskUiState, action: TaskAction): TaskUiState {
  switch (action.type) {
    case 'submit_started':
      return { phase: 'submitting', requestId: action.requestId, text: action.text };

    case 'submit_succeeded':
      if (state.phase !== 'submitting') return state;
      return {
        phase: 'active',
        requestId: state.requestId,
        taskId: action.taskId,
        text: state.text,
        state: action.state,
        summary: null,
        result: null,
        error: null,
        revision: 0,
        unchangedStreak: 0,
        cancelRequested: false,
        pollError: null,
      };

    case 'submit_failed':
      if (state.phase !== 'submitting') return state;
      return { phase: 'submit_failed', requestId: state.requestId, text: state.text, message: action.message };

    case 'attach_existing':
      return {
        phase: 'active',
        requestId: null,
        taskId: action.taskId,
        text: null,
        state: 'running',
        summary: 'Reattached to a task already in progress.',
        result: null,
        error: null,
        revision: 0,
        unchangedStreak: 0,
        cancelRequested: false,
        pollError: null,
      };

    case 'poll_succeeded': {
      if (state.phase !== 'active' || state.taskId !== action.taskId) return state;
      const unchanged = action.revision === state.revision;
      return {
        ...state,
        state: action.state,
        summary: action.summary,
        result: action.result,
        error: action.error,
        revision: action.revision,
        unchangedStreak: unchanged ? state.unchangedStreak + 1 : 0,
        pollError: null,
      };
    }

    case 'poll_failed':
      if (state.phase !== 'active' || state.taskId !== action.taskId) return state;
      return { ...state, pollError: action.message };

    case 'cancel_requested':
      if (state.phase !== 'active') return state;
      return { ...state, cancelRequested: true };

    case 'dismiss':
      return { phase: 'idle' };

    default:
      return state;
  }
}

/** Whether the composer should currently be disabled (duplicate-submit
 * prevention, first layer -- see useTaskPolling.ts / ComposerBar for the
 * synchronous ref-based guard, the second layer). */
export function isTaskInFlight(state: TaskUiState): boolean {
  if (state.phase === 'submitting') return true;
  if (state.phase === 'active') return !isTerminalTaskState(state.state);
  return false;
}
