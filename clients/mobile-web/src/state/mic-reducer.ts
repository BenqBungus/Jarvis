export type MicPermission = 'unavailable' | 'prompt' | 'granted' | 'denied';

export interface MicState {
  /** From capabilities.features.voice. Today's real contract always sends
   * false -- push-to-talk stays disabled regardless of OS mic permission
   * until a real capabilities response enables it. Never flipped true by
   * guesswork. */
  voiceCapable: boolean;
  permission: MicPermission;
}

export type MicAction =
  | { type: 'voice_capability_updated'; voiceCapable: boolean }
  | { type: 'permission_updated'; permission: MicPermission };

export const initialMicState: MicState = { voiceCapable: false, permission: 'prompt' };

export function micReducer(state: MicState, action: MicAction): MicState {
  switch (action.type) {
    case 'voice_capability_updated':
      return { ...state, voiceCapable: action.voiceCapable };
    case 'permission_updated':
      return { ...state, permission: action.permission };
    default:
      return state;
  }
}

export type PushToTalkAvailability = 'unavailable_not_enabled' | 'unavailable_permission' | 'ready';

/** Push-to-talk is rendered in every build (the brief asks for the control
 * to exist with a clear unavailable state, not to be hidden) but is only
 * ever enabled when BOTH the server has actually turned voice on AND the
 * browser has granted mic permission. */
export function pushToTalkAvailability(state: MicState): PushToTalkAvailability {
  if (!state.voiceCapable) return 'unavailable_not_enabled';
  if (state.permission !== 'granted') return 'unavailable_permission';
  return 'ready';
}
