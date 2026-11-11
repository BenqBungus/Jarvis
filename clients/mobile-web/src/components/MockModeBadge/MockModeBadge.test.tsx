import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/preact';
import { MockModeBadge } from './MockModeBadge';

describe('MockModeBadge', () => {
  it('renders an unmissable label in mock mode', () => {
    render(<MockModeBadge mode="mock" />);
    const badge = screen.getByTestId('mock-mode-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent(/mock mode/i);
    expect(badge).toHaveTextContent(/not your laptop/i);
  });

  it('renders nothing in transport mode', () => {
    render(<MockModeBadge mode="transport" />);
    expect(screen.queryByTestId('mock-mode-badge')).not.toBeInTheDocument();
  });
});
