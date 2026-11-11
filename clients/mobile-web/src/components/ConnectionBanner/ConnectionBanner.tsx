import type { ConnectionSummary } from '../../state/connection-reducer';
import styles from './ConnectionBanner.module.css';

const COPY: Record<ConnectionSummary, { label: string; tone: 'ok' | 'warn' | 'bad' }> = {
  checking: { label: 'Connecting…', tone: 'warn' },
  online: { label: 'Connected', tone: 'ok' },
  offline_browser: { label: 'Offline — no network connection', tone: 'bad' },
  offline_companion: { label: 'Offline — laptop unreachable', tone: 'bad' },
  error: { label: 'Connection error', tone: 'bad' },
};

export function ConnectionBanner({ summary, deviceName }: { summary: ConnectionSummary; deviceName?: string }) {
  const copy = COPY[summary];
  const label = summary === 'online' && deviceName ? `Connected to ${deviceName}` : copy.label;
  return (
    <div class={`${styles.banner} ${styles[copy.tone]}`} role="status" data-testid="connection-banner" data-summary={summary}>
      <span class={styles.dot} aria-hidden="true" />
      {label}
    </div>
  );
}
