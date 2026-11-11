import { describe, expect, it } from 'vitest';
import { initialMicState, micReducer, pushToTalkAvailability } from './mic-reducer';

describe('pushToTalkAvailability', () => {
  it('is unavailable_not_enabled under today\'s real contract (voice: false), regardless of OS permission', () => {
    expect(pushToTalkAvailability({ voiceCapable: false, permission: 'granted' })).toBe('unavailable_not_enabled');
    expect(pushToTalkAvailability({ voiceCapable: false, permission: 'denied' })).toBe('unavailable_not_enabled');
  });

  it('is unavailable_permission when the server enables voice but the browser has not granted mic access', () => {
    expect(pushToTalkAvailability({ voiceCapable: true, permission: 'prompt' })).toBe('unavailable_permission');
    expect(pushToTalkAvailability({ voiceCapable: true, permission: 'denied' })).toBe('unavailable_permission');
    expect(pushToTalkAvailability({ voiceCapable: true, permission: 'unavailable' })).toBe('unavailable_permission');
  });

  it('is ready only once both the server and the browser agree', () => {
    expect(pushToTalkAvailability({ voiceCapable: true, permission: 'granted' })).toBe('ready');
  });
});

describe('micReducer', () => {
  it('never flips voiceCapable true on its own -- only via an explicit capability update', () => {
    expect(initialMicState.voiceCapable).toBe(false);
    const state = micReducer(initialMicState, { type: 'voice_capability_updated', voiceCapable: true });
    expect(state.voiceCapable).toBe(true);
  });

  it('tracks permission updates independently of voiceCapable', () => {
    const state = micReducer(initialMicState, { type: 'permission_updated', permission: 'granted' });
    expect(state).toMatchObject({ voiceCapable: false, permission: 'granted' });
  });
});
