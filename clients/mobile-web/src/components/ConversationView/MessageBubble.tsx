import type { ConversationEntry } from '../../hooks/useConversationLog';
import styles from './ConversationView.module.css';

export function MessageBubble({ entry }: { entry: ConversationEntry }) {
  return (
    <div class={styles.exchange} data-testid="conversation-entry">
      <div class={`${styles.bubble} ${styles.user}`}>{entry.userText}</div>
      <div class={`${styles.bubble} ${styles.assistant} ${outcomeClass(entry.outcome.kind)}`}>
        {renderOutcome(entry)}
      </div>
    </div>
  );
}

function outcomeClass(kind: string): string {
  if (kind === 'failed') return styles.failed;
  if (kind === 'cancelled') return styles.cancelled;
  return '';
}

function renderOutcome(entry: ConversationEntry) {
  switch (entry.outcome.kind) {
    case 'pending':
      return <span class="animated-pulse">Working…</span>;
    case 'completed':
      return <span>{String(entry.outcome.result)}</span>;
    case 'failed':
      return <span>{entry.outcome.error?.message ?? 'Failed.'}</span>;
    case 'cancelled':
      return <span>Cancelled.</span>;
    default:
      return null;
  }
}
