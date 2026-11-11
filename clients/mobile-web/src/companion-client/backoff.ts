/**
 * Contract: "Poll while active; back off when unchanged." We use the
 * contract's own `revision` field as the "did anything change" signal --
 * see useTaskPolling.ts for where this is applied.
 */
export const POLL_BACKOFF_MS = [1000, 1000, 2000, 3000, 5000, 8000] as const;

/** Delay before the first poll after a 202 response. Short enough that fast
 * mock/local tasks feel responsive, long enough not to hammer a real server
 * for a task that hasn't even been dequeued yet. */
export const INITIAL_POLL_DELAY_MS = 500;

/** How long the connection heartbeat (GET /v1/status) waits between checks
 * while no task is actively being polled. */
export const STATUS_HEARTBEAT_MS = 15_000;

export function nextPollDelayMs(unchangedStreak: number): number {
  const index = Math.min(Math.max(unchangedStreak, 0), POLL_BACKOFF_MS.length - 1);
  return POLL_BACKOFF_MS[index];
}
