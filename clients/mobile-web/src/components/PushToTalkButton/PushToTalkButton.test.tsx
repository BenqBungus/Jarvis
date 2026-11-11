import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/preact';
import { PushToTalkButton } from './PushToTalkButton';
import type { MicState } from '../../state/mic-reducer';

describe('PushToTalkButton', () => {
  it('is disabled and clearly labeled when the server has not enabled voice (today\'s real contract)', () => {
    const mic: MicState = { voiceCapable: false, permission: 'prompt' };
    render(<PushToTalkButton mic={mic} onRequestAccess={vi.fn()} />);
    const button = screen.getByTestId('push-to-talk-button');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/not available yet/i);
  });

  it('stays disabled purely from OS permission even when voice is capable', () => {
    const mic: MicState = { voiceCapable: true, permission: 'denied' };
    render(<PushToTalkButton mic={mic} onRequestAccess={vi.fn()} />);
    const button = screen.getByTestId('push-to-talk-button');
    expect(button).toHaveAttribute('data-availability', 'unavailable_permission');
    expect(button).toHaveTextContent(/denied/i);
  });

  it('is enabled only once both capability and permission are granted', () => {
    const mic: MicState = { voiceCapable: true, permission: 'granted' };
    render(<PushToTalkButton mic={mic} onRequestAccess={vi.fn()} />);
    const button = screen.getByTestId('push-to-talk-button');
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('data-availability', 'ready');
  });

  it('requests mic access when tapped while only permission is missing', () => {
    const onRequestAccess = vi.fn();
    const mic: MicState = { voiceCapable: true, permission: 'prompt' };
    render(<PushToTalkButton mic={mic} onRequestAccess={onRequestAccess} />);
    screen.getByTestId('push-to-talk-button').click();
    expect(onRequestAccess).toHaveBeenCalledOnce();
  });
});
