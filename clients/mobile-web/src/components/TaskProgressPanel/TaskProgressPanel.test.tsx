import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/preact';
import { TaskProgressPanel } from './TaskProgressPanel';
import type { TaskUiState } from '../../state/task-reducer';

describe('TaskProgressPanel', () => {
  it('renders nothing when idle', () => {
    render(<TaskProgressPanel task={{ phase: 'idle' }} onCancel={vi.fn()} onDismiss={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.queryByTestId('task-progress')).not.toBeInTheDocument();
  });

  it('never shows an invented progress percentage', () => {
    const task: TaskUiState = {
      phase: 'active',
      requestId: 'r1',
      taskId: 't1',
      text: 'do the thing',
      state: 'running',
      summary: 'Running (mock).',
      result: null,
      error: null,
      revision: 2,
      unchangedStreak: 0,
      cancelRequested: false,
      pollError: null,
    };
    render(<TaskProgressPanel task={task} onCancel={vi.fn()} onDismiss={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('offers Cancel while non-terminal and calls onCancel', () => {
    const onCancel = vi.fn();
    const task: TaskUiState = {
      phase: 'active',
      requestId: 'r1',
      taskId: 't1',
      text: 'do the thing',
      state: 'queued',
      summary: null,
      result: null,
      error: null,
      revision: 1,
      unchangedStreak: 0,
      cancelRequested: false,
      pollError: null,
    };
    render(<TaskProgressPanel task={task} onCancel={onCancel} onDismiss={vi.fn()} onRetry={vi.fn()} />);
    screen.getByTestId('cancel-task-button').click();
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('hides Cancel once terminal and offers Dismiss instead', () => {
    const task: TaskUiState = {
      phase: 'active',
      requestId: 'r1',
      taskId: 't1',
      text: 'do the thing',
      state: 'completed',
      summary: 'Completed (mock).',
      result: 'Mock adapter finished simulating this task.',
      error: null,
      revision: 3,
      unchangedStreak: 0,
      cancelRequested: false,
      pollError: null,
    };
    render(<TaskProgressPanel task={task} onCancel={vi.fn()} onDismiss={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.queryByTestId('cancel-task-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('dismiss-task-button')).toBeInTheDocument();
  });

  it('shows a server-error message and no misleading success text', () => {
    const task: TaskUiState = {
      phase: 'active',
      requestId: 'r1',
      taskId: 't1',
      text: 'do the thing',
      state: 'failed',
      summary: 'Failed (mock).',
      result: null,
      error: { code: 'mock_failure', message: 'Simulated failure (mock "fail" scenario).', retryable: true },
      revision: 3,
      unchangedStreak: 0,
      cancelRequested: false,
      pollError: null,
    };
    render(<TaskProgressPanel task={task} onCancel={vi.fn()} onDismiss={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId('task-error')).toHaveTextContent('Simulated failure');
  });

  it('offers Retry after a failed submit and calls onRetry', () => {
    const onRetry = vi.fn();
    const task: TaskUiState = { phase: 'submit_failed', requestId: 'r1', text: 'do the thing', message: 'Could not reach the companion server.' };
    render(<TaskProgressPanel task={task} onCancel={vi.fn()} onDismiss={vi.fn()} onRetry={onRetry} />);
    expect(screen.getByTestId('task-progress')).toHaveTextContent('Could not reach the companion server.');
    screen.getByTestId('retry-submit-button').click();
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
