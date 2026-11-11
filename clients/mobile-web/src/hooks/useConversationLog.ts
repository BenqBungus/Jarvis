import { useEffect, useRef, useState } from 'preact/hooks';
import type { ApiErrorBody } from '../contract/types';
import type { TaskUiState } from '../state/task-reducer';

export type ConversationOutcome =
  | { kind: 'pending' }
  | { kind: 'completed'; result: unknown }
  | { kind: 'failed'; error: ApiErrorBody | null }
  | { kind: 'cancelled' };

export interface ConversationEntry {
  id: string;
  userText: string;
  outcome: ConversationOutcome;
}

/**
 * Session-only history (no persistence -- see README.md's "no storage in
 * v1" note): appends one entry per submitted task, updated in place once it
 * resolves. Not part of task-reducer.ts because it's a presentation-only
 * derived log of *past* tasks, not the live single-active-task state
 * machine that drives polling/cancel.
 */
export function useConversationLog(task: TaskUiState): ConversationEntry[] {
  const [entries, setEntries] = useState<ConversationEntry[]>([]);
  const loggedIds = useRef(new Set<string>());

  useEffect(() => {
    if (task.phase !== 'active') return;
    const id = task.requestId ?? task.taskId;
    if (!loggedIds.current.has(id)) {
      loggedIds.current.add(id);
      setEntries((prev) => [
        ...prev,
        {
          id,
          userText: task.text ?? '(reattached task from before reload — original request text was not saved anywhere)',
          outcome: { kind: 'pending' },
        },
      ]);
    }

    if (task.state === 'completed' || task.state === 'failed' || task.state === 'cancelled') {
      setEntries((prev) =>
        prev.map((entry) =>
          entry.id === id
            ? {
                ...entry,
                outcome:
                  task.state === 'completed'
                    ? { kind: 'completed', result: task.result }
                    : task.state === 'failed'
                      ? { kind: 'failed', error: task.error }
                      : { kind: 'cancelled' },
              }
            : entry,
        ),
      );
    }
  }, [task]);

  return entries;
}
