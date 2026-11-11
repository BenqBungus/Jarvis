import { useEffect, useRef } from 'preact/hooks';
import type { CompanionClient } from '../companion-client/client';
import { STATUS_HEARTBEAT_MS } from '../companion-client/backoff';
import { describeError } from '../companion-client/errors';
import { useAppState } from '../state/app-state';

/**
 * Owns: browser online/offline events, the one-time capabilities fetch, and
 * a periodic GET /v1/status heartbeat (paused while a task poll is already
 * hitting the server -- see useTaskPolling.ts). Also implements
 * reconnect-on-load: if a status response reports an active_task_id and we
 * aren't already tracking a task locally, we attach to it. That's the
 * backend acting as the source of truth for "what's in flight" instead of
 * any local storage (there is no real pairing/token flow yet to persist).
 */
export function useOnlineStatus(client: CompanionClient, taskInFlight: boolean): void {
  const { task, dispatchConnection, dispatchTask } = useAppState();

  // Read via a ref, not the closed-over `task` directly: the heartbeat
  // effect below only re-creates its closure when `taskInFlight` changes,
  // but `task.phase` can change without `taskInFlight` changing (idle ->
  // submit_failed are both "not in flight"), which would otherwise let
  // tick() act on a stale phase.
  const taskPhaseRef = useRef(task.phase);
  taskPhaseRef.current = task.phase;

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleOnline = () => dispatchConnection({ type: 'browser_online', online: true });
    const handleOffline = () => dispatchConnection({ type: 'browser_online', online: false });
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [dispatchConnection]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    client
      .getCapabilities(controller.signal)
      .then((capabilities) => {
        if (!cancelled) dispatchConnection({ type: 'capabilities_loaded', capabilities });
      })
      .catch((error) => {
        if (!cancelled) dispatchConnection({ type: 'capabilities_failed', message: describeError(error) });
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [client, dispatchConnection]);

  useEffect(() => {
    if (taskInFlight) return undefined;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      const controller = new AbortController();
      try {
        const status = await client.getStatus(controller.signal);
        if (cancelled) return;
        dispatchConnection({ type: 'status_loaded', online: status.online, state: status.state });
        if (status.active_task_id && taskPhaseRef.current === 'idle') {
          dispatchTask({ type: 'attach_existing', taskId: status.active_task_id });
        }
      } catch {
        if (!cancelled) dispatchConnection({ type: 'status_failed' });
      }
      if (!cancelled) timer = setTimeout(tick, STATUS_HEARTBEAT_MS);
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [client, dispatchConnection, dispatchTask, taskInFlight]);
}
