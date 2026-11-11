import type { CompanionClient, ClientMode } from './client';
import { MockCompanionAdapter } from './mock-adapter';
import { TransportCompanionAdapter } from './transport-adapter';
import { env } from '../config/env';

/**
 * The single place the app decides mock vs. real transport. Everything else
 * imports CompanionClient (the interface) and calls createCompanionClient()
 * once at startup -- never either adapter class directly.
 *
 * Build-time default comes from VITE_COMPANION_MODE (env.ts), defaulting to
 * 'mock' when unset -- there is no real server, so shipping with 'transport'
 * as a silent default would just be a worse mock (one that fails instead of
 * simulating). A `?mode=` query override is honored ONLY in dev builds
 * (import.meta.env.DEV): a shipped production build can never be redirected
 * at a real endpoint by a crafted URL.
 */
export function createCompanionClient(): CompanionClient {
  const mode = resolveMode();
  if (mode === 'transport') {
    return new TransportCompanionAdapter({ baseUrl: env.companionBaseUrl, token: env.companionDevToken });
  }
  return new MockCompanionAdapter();
}

function resolveMode(): ClientMode {
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const override = new URLSearchParams(window.location.search).get('mode');
    if (override === 'mock' || override === 'transport') return override;
  }
  return env.companionMode;
}
