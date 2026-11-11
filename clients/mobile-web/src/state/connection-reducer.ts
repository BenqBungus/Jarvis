import type { CapabilitiesResponse } from '../contract/types';

export interface ConnectionState {
  browserOnline: boolean;
  capabilities: CapabilitiesResponse | null;
  capabilitiesError: string | null;
  companionOnline: boolean | null; // null = not checked yet
  companionState: string | null;
}

export type ConnectionAction =
  | { type: 'browser_online'; online: boolean }
  | { type: 'capabilities_loaded'; capabilities: CapabilitiesResponse }
  | { type: 'capabilities_failed'; message: string }
  | { type: 'status_loaded'; online: boolean; state: string }
  | { type: 'status_failed' };

export const initialConnectionState: ConnectionState = {
  browserOnline: typeof navigator === 'undefined' ? true : navigator.onLine,
  capabilities: null,
  capabilitiesError: null,
  companionOnline: null,
  companionState: null,
};

export function connectionReducer(state: ConnectionState, action: ConnectionAction): ConnectionState {
  switch (action.type) {
    case 'browser_online':
      return { ...state, browserOnline: action.online };
    case 'capabilities_loaded':
      return { ...state, capabilities: action.capabilities, capabilitiesError: null };
    case 'capabilities_failed':
      return { ...state, capabilitiesError: action.message };
    case 'status_loaded':
      return { ...state, companionOnline: action.online, companionState: action.state };
    case 'status_failed':
      return { ...state, companionOnline: false, companionState: null };
    default:
      return state;
  }
}

export type ConnectionSummary = 'checking' | 'online' | 'offline_browser' | 'offline_companion' | 'error';

/** One derived status the ConnectionBanner renders from -- computed, not
 * stored, so the banner can never disagree with the underlying state. */
export function summarizeConnection(state: ConnectionState): ConnectionSummary {
  if (!state.browserOnline) return 'offline_browser';
  if (state.capabilitiesError) return 'error';
  if (state.companionOnline === false) return 'offline_companion';
  if (state.companionOnline === true && state.capabilities) return 'online';
  return 'checking';
}
