/**
 * One request_id per logical task submission (contract: "UUID; idempotent
 * per paired device"). Callers generate this once and reuse it verbatim on
 * manual retry after a failed submit -- never mint a fresh one for the same
 * logical message, or the server can't deduplicate a resend after a timeout.
 */
export function generateRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Fallback for any environment without crypto.randomUUID (older WebKit,
  // non-secure-context test runners). Not cryptographically strong, but this
  // is a deduplication key, not a secret.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
