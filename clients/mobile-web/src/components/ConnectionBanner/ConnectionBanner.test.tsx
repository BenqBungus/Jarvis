import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/preact';
import { ConnectionBanner } from './ConnectionBanner';

describe('ConnectionBanner', () => {
  it('shows an honest offline label when the browser has no network', () => {
    render(<ConnectionBanner summary="offline_browser" />);
    expect(screen.getByTestId('connection-banner')).toHaveTextContent(/offline/i);
  });

  it('shows an honest offline label when only the companion device is unreachable', () => {
    render(<ConnectionBanner summary="offline_companion" />);
    expect(screen.getByTestId('connection-banner')).toHaveTextContent(/laptop unreachable/i);
  });

  it('shows the device name once actually online', () => {
    render(<ConnectionBanner summary="online" deviceName="Jarvis PC" />);
    expect(screen.getByTestId('connection-banner')).toHaveTextContent('Connected to Jarvis PC');
  });

  it('never claims online while checking', () => {
    render(<ConnectionBanner summary="checking" />);
    expect(screen.getByTestId('connection-banner')).not.toHaveTextContent(/connected/i);
  });
});
