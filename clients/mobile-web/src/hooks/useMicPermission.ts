import { useCallback, useEffect } from 'preact/hooks';
import { useAppState } from '../state/app-state';

/**
 * Syncs mic.voiceCapable from the server's actual capabilities response
 * (never guessed), and -- only once voice is actually capable -- probes the
 * browser's own mic permission state. There is no reason to ask the browser
 * about microphone permission for a feature the server hasn't turned on;
 * doing so could itself trigger a permission prompt the user has no reason
 * to see yet.
 */
export function useMicPermission() {
  const { connection, mic, dispatchMic } = useAppState();
  const voiceCapable = connection.capabilities?.features.voice ?? false;

  useEffect(() => {
    dispatchMic({ type: 'voice_capability_updated', voiceCapable });
  }, [voiceCapable, dispatchMic]);

  useEffect(() => {
    if (!voiceCapable) return undefined;
    if (typeof navigator === 'undefined' || !navigator.permissions?.query) {
      dispatchMic({ type: 'permission_updated', permission: 'prompt' });
      return undefined;
    }
    let cancelled = false;
    // TS lib.dom's PermissionName union doesn't include 'microphone' in
    // every TS version; the browser API itself supports it widely.
    navigator.permissions
      .query({ name: 'microphone' as PermissionName })
      .then((status) => {
        if (cancelled) return;
        dispatchMic({ type: 'permission_updated', permission: status.state });
        status.onchange = () => {
          if (!cancelled) dispatchMic({ type: 'permission_updated', permission: status.state });
        };
      })
      .catch(() => {
        if (!cancelled) dispatchMic({ type: 'permission_updated', permission: 'prompt' });
      });
    return () => {
      cancelled = true;
    };
  }, [voiceCapable, dispatchMic]);

  const requestMicAccess = useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      dispatchMic({ type: 'permission_updated', permission: 'unavailable' });
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      for (const track of stream.getTracks()) track.stop();
      dispatchMic({ type: 'permission_updated', permission: 'granted' });
    } catch {
      dispatchMic({ type: 'permission_updated', permission: 'denied' });
    }
  }, [dispatchMic]);

  return { mic, requestMicAccess };
}
