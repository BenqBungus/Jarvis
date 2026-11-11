import type { ClientMode } from '../companion-client/client';

function readMode(): ClientMode {
  const raw = import.meta.env.VITE_COMPANION_MODE;
  return raw === 'transport' ? 'transport' : 'mock';
}

export const env = {
  companionMode: readMode(),
  companionBaseUrl: import.meta.env.VITE_COMPANION_BASE_URL ?? '',
  // Placeholder only, per .env.example -- there is no real pairing protocol
  // yet, so there is no real token to read in any environment today.
  companionDevToken: import.meta.env.VITE_COMPANION_DEV_TOKEN ?? '',
} as const;
