import { useState } from 'preact/hooks';
import type { JSX } from 'preact';
import { TASK_TEXT_MAX_CHARACTERS } from '../../contract/types';
import styles from './ComposerBar.module.css';

export function ComposerBar({
  disabled,
  onSubmit,
}: {
  /** True while a task is in flight (see isTaskInFlight) -- this is the
   * first layer of duplicate-submit prevention; useTaskPolling's
   * isSubmittingRef is the second, synchronous layer. */
  disabled: boolean;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState('');

  function handleSubmit(event: JSX.TargetedEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed.slice(0, TASK_TEXT_MAX_CHARACTERS));
    setText('');
  }

  return (
    <form class={styles.bar} onSubmit={handleSubmit}>
      <textarea
        class={styles.input}
        value={text}
        disabled={disabled}
        maxLength={TASK_TEXT_MAX_CHARACTERS}
        placeholder={disabled ? 'Waiting…' : 'Message Jarvis…'}
        rows={1}
        data-testid="composer-input"
        onInput={(event) => setText((event.target as HTMLTextAreaElement).value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            (event.currentTarget as HTMLTextAreaElement).form?.requestSubmit();
          }
        }}
      />
      <button type="submit" disabled={disabled || !text.trim()} data-testid="composer-submit">
        Send
      </button>
    </form>
  );
}
