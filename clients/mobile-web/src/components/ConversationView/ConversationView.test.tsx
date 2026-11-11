import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/preact';
import { ConversationView } from './ConversationView';
import type { ConversationEntry } from '../../hooks/useConversationLog';

describe('ConversationView', () => {
  it('shows an empty-state hint with no history yet', () => {
    render(<ConversationView entries={[]} />);
    expect(screen.getByTestId('conversation-empty')).toBeInTheDocument();
  });

  it('renders the user text and a pending indicator for an in-flight entry', () => {
    const entries: ConversationEntry[] = [{ id: 't1', userText: 'open notepad', outcome: { kind: 'pending' } }];
    render(<ConversationView entries={entries} />);
    expect(screen.getByText('open notepad')).toBeInTheDocument();
    expect(screen.getByText(/working/i)).toBeInTheDocument();
  });

  it('renders a completed result honestly labeled as fixture text, never a fabricated telemetry value', () => {
    const entries: ConversationEntry[] = [
      {
        id: 't1',
        userText: 'check something',
        outcome: { kind: 'completed', result: 'Mock adapter finished simulating this task. This is fixture data, not a result from your laptop.' },
      },
    ];
    render(<ConversationView entries={entries} />);
    expect(screen.getByText(/fixture data, not a result from your laptop/i)).toBeInTheDocument();
  });

  it('renders a failed outcome using the error message, not a success-looking bubble', () => {
    const entries: ConversationEntry[] = [
      {
        id: 't1',
        userText: 'do something',
        outcome: { kind: 'failed', error: { code: 'mock_failure', message: 'Simulated failure.', retryable: true } },
      },
    ];
    render(<ConversationView entries={entries} />);
    expect(screen.getByText('Simulated failure.')).toBeInTheDocument();
  });
});
