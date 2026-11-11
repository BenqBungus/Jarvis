import { describe, expect, it } from 'vitest';
import { nextPollDelayMs, POLL_BACKOFF_MS } from './backoff';

describe('nextPollDelayMs', () => {
  it('starts at the fast end when nothing has been unchanged yet', () => {
    expect(nextPollDelayMs(0)).toBe(POLL_BACKOFF_MS[0]);
  });

  it('advances through the table as the unchanged streak grows', () => {
    expect(nextPollDelayMs(1)).toBe(POLL_BACKOFF_MS[1]);
    expect(nextPollDelayMs(2)).toBe(POLL_BACKOFF_MS[2]);
    expect(nextPollDelayMs(3)).toBe(POLL_BACKOFF_MS[3]);
  });

  it('caps at the slowest configured delay rather than growing unbounded', () => {
    expect(nextPollDelayMs(POLL_BACKOFF_MS.length - 1)).toBe(POLL_BACKOFF_MS[POLL_BACKOFF_MS.length - 1]);
    expect(nextPollDelayMs(999)).toBe(POLL_BACKOFF_MS[POLL_BACKOFF_MS.length - 1]);
  });

  it('never returns a delay for a negative streak (defensive floor)', () => {
    expect(nextPollDelayMs(-5)).toBe(POLL_BACKOFF_MS[0]);
  });
});
