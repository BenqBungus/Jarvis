import type { ApiErrorBody } from '../contract/types';

/** The server rejected the request and returned the contract's error shape. */
export class CompanionApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;

  constructor(body: ApiErrorBody) {
    super(body.message);
    this.name = 'CompanionApiError';
    this.code = body.code;
    this.retryable = body.retryable;
  }
}

/** The request never reached (or never got a response from) the companion
 * server -- fetch threw, DNS failed, TLS failed, offline, etc. Always
 * retryable in principle (the caller decides when). */
export class CompanionNetworkError extends Error {
  readonly cause?: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'CompanionNetworkError';
    this.cause = cause;
  }
}

/** A request was aborted because it exceeded its own timeout, not because
 * the caller cancelled it. Distinguished from a caller-initiated
 * AbortController abort so the UI doesn't show a spurious error for an
 * intentional cancel. */
export class CompanionTimeoutError extends Error {
  constructor(message = 'Request timed out.') {
    super(message);
    this.name = 'CompanionTimeoutError';
  }
}

export function isRetryableError(error: unknown): boolean {
  if (error instanceof CompanionApiError) return error.retryable;
  if (error instanceof CompanionNetworkError) return true;
  if (error instanceof CompanionTimeoutError) return true;
  return false;
}

export function describeError(error: unknown): string {
  if (error instanceof CompanionApiError) return error.message;
  if (error instanceof CompanionNetworkError) return 'Could not reach the companion server.';
  if (error instanceof CompanionTimeoutError) return 'The companion server took too long to respond.';
  if (error instanceof Error) return error.message;
  return 'Something unexpected went wrong.';
}
