import { useEffect, useRef } from 'preact/hooks';
import type { ConversationEntry } from '../../hooks/useConversationLog';
import { MessageBubble } from './MessageBubble';
import styles from './ConversationView.module.css';

export function ConversationView({ entries }: { entries: ConversationEntry[] }) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [entries.length]);

  if (entries.length === 0) {
    return (
      <div class={styles.empty} data-testid="conversation-empty">
        Ask Jarvis something below to get started.
      </div>
    );
  }

  return (
    <div class={styles.view} data-testid="conversation-view">
      {entries.map((entry) => (
        <MessageBubble key={entry.id} entry={entry} />
      ))}
      <div ref={endRef} />
    </div>
  );
}
