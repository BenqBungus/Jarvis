import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/preact';
import { ErrorToast } from './ErrorToast';

describe('ErrorToast', () => {
  it('renders nothing when there is no message', () => {
    render(<ErrorToast message={null} onDismiss={vi.fn()} />);
    expect(screen.queryByTestId('error-toast')).not.toBeInTheDocument();
  });

  it('renders the message and calls onDismiss when closed', () => {
    const onDismiss = vi.fn();
    render(<ErrorToast message="Could not reach the companion server." onDismiss={onDismiss} />);
    expect(screen.getByTestId('error-toast')).toHaveTextContent('Could not reach the companion server.');
    screen.getByLabelText('Dismiss').click();
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
