import type { TaskUiState } from '../../state/task-reducer';
import styles from './TaskProgressPanel.module.css';

// Discrete named states only -- deliberately no invented progress
// percentage. The contract has no notion of "38% done" and fabricating one
// would be exactly the kind of fake-success signal this client must never
// show.
const STATE_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  awaiting_desktop_approval: 'Waiting for approval on your laptop',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export function TaskProgressPanel({
  task,
  onCancel,
  onDismiss,
  onRetry,
}: {
  task: TaskUiState;
  onCancel: () => void;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  if (task.phase === 'idle') return null;

  if (task.phase === 'submitting') {
    return (
      <div class={styles.panel} data-testid="task-progress" data-phase="submitting">
        <p class={`${styles.state} animated-pulse`}>Sending…</p>
      </div>
    );
  }

  if (task.phase === 'submit_failed') {
    return (
      <div class={styles.panel} data-testid="task-progress" data-phase="submit_failed">
        <p class={styles.error}>Could not send: {task.message}</p>
        <div class={styles.actions}>
          <button type="button" onClick={onRetry} data-testid="retry-submit-button">
            Retry
          </button>
          <button type="button" onClick={onDismiss} data-testid="dismiss-task-button">
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  const canCancel = !task.cancelRequested && !['completed', 'failed', 'cancelled'].includes(task.state);
  const isTerminal = ['completed', 'failed', 'cancelled'].includes(task.state);

  return (
    <div class={styles.panel} data-testid="task-progress" data-phase="active" data-state={task.state}>
      <p class={task.state === 'running' || task.state === 'queued' ? `${styles.state} animated-pulse` : styles.state}>
        {STATE_LABEL[task.state] ?? task.state}
        {task.cancelRequested && !isTerminal ? ' — cancelling…' : ''}
      </p>
      {task.summary && <p class={styles.summary}>{task.summary}</p>}
      {task.state === 'failed' && task.error && (
        <p class={styles.error} data-testid="task-error">
          {task.error.message}
        </p>
      )}
      {task.state === 'completed' && task.result != null && (
        <p class={styles.result} data-testid="task-result">
          {String(task.result)}
        </p>
      )}
      {task.pollError && (
        <p class={styles.transientError} role="status">
          Reconnecting… ({task.pollError})
        </p>
      )}
      <div class={styles.actions}>
        {canCancel && (
          <button type="button" onClick={onCancel} data-testid="cancel-task-button">
            Cancel
          </button>
        )}
        {isTerminal && (
          <button type="button" onClick={onDismiss} data-testid="dismiss-task-button">
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}
