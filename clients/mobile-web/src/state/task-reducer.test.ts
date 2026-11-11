import { describe, expect, it } from 'vitest';
import { initialTaskState, isTaskInFlight, taskReducer } from './task-reducer';

describe('taskReducer', () => {
  it('idle -> submitting -> active carries the request_id and text through', () => {
    let state = taskReducer(initialTaskState, { type: 'submit_started', requestId: 'r1', text: 'open notepad' });
    expect(state).toMatchObject({ phase: 'submitting', requestId: 'r1', text: 'open notepad' });

    state = taskReducer(state, { type: 'submit_succeeded', taskId: 't1', state: 'queued' });
    expect(state).toMatchObject({ phase: 'active', requestId: 'r1', taskId: 't1', text: 'open notepad', state: 'queued', revision: 0 });
  });

  it('a submit failure preserves the request_id and text for retry', () => {
    let state = taskReducer(initialTaskState, { type: 'submit_started', requestId: 'r1', text: 'open notepad' });
    state = taskReducer(state, { type: 'submit_failed', message: 'network down' });
    expect(state).toMatchObject({ phase: 'submit_failed', requestId: 'r1', text: 'open notepad', message: 'network down' });
  });

  it('attach_existing has no request_id or text -- it never invents the original request', () => {
    const state = taskReducer(initialTaskState, { type: 'attach_existing', taskId: 't1' });
    expect(state).toMatchObject({ phase: 'active', requestId: null, taskId: 't1', text: null });
  });

  it('poll_succeeded is ignored for a task_id that is not the one being tracked (stale-response guard)', () => {
    let state = taskReducer(initialTaskState, { type: 'submit_started', requestId: 'r1', text: 'x' });
    state = taskReducer(state, { type: 'submit_succeeded', taskId: 't1', state: 'queued' });
    const before = state;
    state = taskReducer(state, {
      type: 'poll_succeeded',
      taskId: 'some-other-task',
      state: 'completed',
      summary: null,
      result: 'should not apply',
      error: null,
      revision: 5,
    });
    expect(state).toBe(before);
  });

  it('poll_succeeded resets unchangedStreak when revision changes and increments it when unchanged', () => {
    let state = taskReducer(initialTaskState, { type: 'submit_started', requestId: 'r1', text: 'x' });
    state = taskReducer(state, { type: 'submit_succeeded', taskId: 't1', state: 'queued' });
    state = taskReducer(state, { type: 'poll_succeeded', taskId: 't1', state: 'running', summary: null, result: null, error: null, revision: 1 });
    expect(state).toMatchObject({ unchangedStreak: 0, revision: 1 });
    state = taskReducer(state, { type: 'poll_succeeded', taskId: 't1', state: 'running', summary: null, result: null, error: null, revision: 1 });
    expect(state).toMatchObject({ unchangedStreak: 1, revision: 1 });
    state = taskReducer(state, { type: 'poll_succeeded', taskId: 't1', state: 'completed', summary: null, result: 'done', error: null, revision: 2 });
    expect(state).toMatchObject({ unchangedStreak: 0, revision: 2 });
  });

  it('a transient poll_failed keeps the last-known-good fields, it does not blank them out', () => {
    let state = taskReducer(initialTaskState, { type: 'submit_started', requestId: 'r1', text: 'x' });
    state = taskReducer(state, { type: 'submit_succeeded', taskId: 't1', state: 'queued' });
    state = taskReducer(state, { type: 'poll_succeeded', taskId: 't1', state: 'running', summary: 'still going', result: null, error: null, revision: 1 });
    state = taskReducer(state, { type: 'poll_failed', taskId: 't1', message: 'flaky network blip' });
    expect(state).toMatchObject({ state: 'running', summary: 'still going', pollError: 'flaky network blip' });
  });

  it('cancel_requested sets an optimistic flag without changing the reported task state', () => {
    let state = taskReducer(initialTaskState, { type: 'submit_started', requestId: 'r1', text: 'x' });
    state = taskReducer(state, { type: 'submit_succeeded', taskId: 't1', state: 'queued' });
    state = taskReducer(state, { type: 'cancel_requested' });
    expect(state).toMatchObject({ cancelRequested: true, state: 'queued' });
  });

  it('dismiss always returns to idle', () => {
    let state = taskReducer(initialTaskState, { type: 'submit_started', requestId: 'r1', text: 'x' });
    state = taskReducer(state, { type: 'dismiss' });
    expect(state).toEqual({ phase: 'idle' });
  });
});

describe('isTaskInFlight', () => {
  it('is false when idle', () => {
    expect(isTaskInFlight({ phase: 'idle' })).toBe(false);
  });

  it('is true while submitting', () => {
    expect(isTaskInFlight({ phase: 'submitting', requestId: 'r1', text: 'x' })).toBe(true);
  });

  it('is false after a submit failure (composer must re-enable so the user can retry/edit)', () => {
    expect(isTaskInFlight({ phase: 'submit_failed', requestId: 'r1', text: 'x', message: 'boom' })).toBe(false);
  });

  it('is true for a non-terminal active task and false once terminal', () => {
    const base = {
      phase: 'active' as const,
      requestId: 'r1',
      taskId: 't1',
      text: 'x',
      summary: null,
      result: null,
      error: null,
      revision: 0,
      unchangedStreak: 0,
      cancelRequested: false,
      pollError: null,
    };
    expect(isTaskInFlight({ ...base, state: 'running' })).toBe(true);
    expect(isTaskInFlight({ ...base, state: 'awaiting_desktop_approval' })).toBe(true);
    expect(isTaskInFlight({ ...base, state: 'completed' })).toBe(false);
    expect(isTaskInFlight({ ...base, state: 'failed' })).toBe(false);
    expect(isTaskInFlight({ ...base, state: 'cancelled' })).toBe(false);
  });
});
