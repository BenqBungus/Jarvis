import type { MicState } from '../../state/mic-reducer';
import { pushToTalkAvailability } from '../../state/mic-reducer';
import styles from './PushToTalkButton.module.css';

const UNAVAILABLE_LABEL: Record<'unavailable_not_enabled' | 'unavailable_permission', string> = {
  unavailable_not_enabled: 'Voice is not enabled for this device yet',
  unavailable_permission: 'Microphone access needed',
};

/**
 * Always rendered -- the brief asks for a clear unavailable state, not a
 * hidden control. Enabling this is gated on capabilities.features.voice
 * (currently false in the real contract) AND browser mic permission; it is
 * never enabled by guesswork ahead of what the server actually reports.
 */
export function PushToTalkButton({ mic, onRequestAccess }: { mic: MicState; onRequestAccess: () => void }) {
  const availability = pushToTalkAvailability(mic);

  if (availability === 'ready') {
    return (
      <button type="button" class={styles.button} data-testid="push-to-talk-button" data-availability={availability}>
        Hold to talk
      </button>
    );
  }

  if (availability === 'unavailable_permission') {
    // Visually muted (styles.disabled) but a real, clickable button: tapping
    // it is the actual permission request, so it must not be aria-disabled.
    return (
      <button
        type="button"
        class={`${styles.button} ${styles.disabled}`}
        data-testid="push-to-talk-button"
        data-availability={availability}
        onClick={onRequestAccess}
        title={UNAVAILABLE_LABEL.unavailable_permission}
      >
        {mic.permission === 'denied' ? 'Microphone access denied — tap to retry' : 'Enable microphone'}
      </button>
    );
  }

  return (
    <button
      type="button"
      class={`${styles.button} ${styles.disabled}`}
      data-testid="push-to-talk-button"
      data-availability={availability}
      disabled
      title={UNAVAILABLE_LABEL.unavailable_not_enabled}
    >
      Voice (not available yet)
    </button>
  );
}
