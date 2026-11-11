import type { ClientMode } from '../../companion-client/client';
import styles from './MockModeBadge.module.css';

export function MockModeBadge({ mode }: { mode: ClientMode }) {
  if (mode !== 'mock') return null;
  return (
    <div class={styles.badge} role="status" data-testid="mock-mode-badge">
      MOCK MODE — fixture data, not your laptop
    </div>
  );
}
