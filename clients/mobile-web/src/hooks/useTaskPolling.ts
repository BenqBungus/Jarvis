import { useCallback, useEffect, useRef } from 'preact/hooks';
import type { CompanionClient } from '../companion-client/client';
import { INITIAL_POLL_DELAY_MS, nextPollDelayMs } from '../companion-client/backoff';
import { describeError } from '../companion-client/errors';
import { generateRequestId } from '../companion-client/request-id';
import { isTerminalTaskState } from '../contract/types';
import { useAppState } from '../state/app-state';

/**
 * Owns the whole task lifecycle: submit, poll-with-backoff against
 * GET /v1/tasks/{id}, and cancel. Backoff/"did anything change" bookkeeping
 * lives in local refs inside this hook's effect, not in the reducer's
 * `unchangedStreak` field -- reading component state back inside a
 * recursive setTimeout closure is exactly the kind of stale-closure trap
 * that's easy to get subtly wrong, so the poll loop is entirely
 * self-contained and only *reports* its findings to the reducer.
 */
export function useTaskPolling(client: CompanionClient) {
  const { task, dispatchTask } = useAppState();
  const taskId = task.phase === 'active' ? task.taskId : null;
  const isSubmittingRef = useRef(false);

  useEffect(() => {
    if (!taskId) return undefined;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastRevision = 0; // matches the reducer's initial revision on submit_succeeded/attach_existing
    let unchangedStreak = 0;

    async function poll() {
      const controller = new AbortController();
      try {
        const resource = await client.getTask(taskId as string, controller.signal);
        if (cancelled || resource.task_id !== taskId) return; // stale-task guard
        const unchanged = resource.revision === lastRevision;
        lastRevision = resource.revision;
        unchangedStreak = unchanged ? unchangedStreak + 1 : 0;
        dispatchTask({
          type: 'poll_succeeded',
          taskId: resource.task_id,
          state: resource.state,
          summary: resource.summary,
          result: resource.result,
          error: resource.error,
          revision: resource.revision,
        });
        if (isTerminalTaskState(resource.state)) return; // done polling
        if (!cancelled) timer = setTimeout(poll, nextPollDelayMs(unchangedStreak));
      } catch (error) {
        if (cancelled) return;
        dispatchTask({ type: 'poll_failed', taskId: taskId as string, message: describeError(error) });
        if (!cancelled) timer = setTimeout(poll, nextPollDelayMs(unchangedStreak));
      }
    }

    timer = setTimeout(poll, INITIAL_POLL_DELAY_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [client, taskId, dispatchTask]);

  const performSubmit = useCallback(
    async (requestId: string, text: string) => {
      if (isSubmittingRef.current) return; // synchronous guard: a double-tap within the same tick can't race past this
      isSubmittingRef.current = true;
      dispatchTask({ type: 'submit_started', requestId, text });
      try {
        const response = await client.submitTask({ requestId, text });
        dispatchTask({ type: 'submit_succeeded', taskId: response.task_id, state: response.state });
      } catch (error) {
        dispatchTask({ type: 'submit_failed', message: describeError(error) });
      } finally {
        isSubmittingRef.current = false;
      }
    },
    [client, dispatchTask],
  );

  const submit = useCallback(
    (text: string) => performSubmit(generateRequestId(), text),
    [performSubmit],
  );

  /** Contract: "Do not resend a task after a timeout without the same
   * request_id." Reuses the identical request_id from the failed attempt --
   * never mints a fresh one for the same logical message. Only meaningful
   * from the 'submit_failed' phase; a no-op otherwise. */
  const retry = useCallback(() => {
    if (task.phase !== 'submit_failed') return;
    void performSubmit(task.requestId, task.text);
  }, [task, performSubmit]);

  const cancel = useCallback(async () => {
    if (task.phase !== 'active') return;
    const activeTaskId = task.taskId;
    dispatchTask({ type: 'cancel_requested' });
    try {
      await client.cancelTask(activeTaskId);
    } catch {
      // Cooperative cancel per the contract; the poll loop keeps running
      // and will reflect whatever state the task actually settles into.
      // A failed cancel *request* isn't a task error worth surfacing twice.
    }
  }, [client, task, dispatchTask]);

  const dismiss = useCallback(() => dispatchTask({ type: 'dismiss' }), [dispatchTask]);

  return { submit, retry, cancel, dismiss };
}
