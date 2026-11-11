import { describe, expect, it } from 'vitest';
import { generateRequestId } from './request-id';

describe('generateRequestId', () => {
  it('generates a UUID-shaped string', () => {
    const id = generateRequestId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  });

  it('never generates the same id twice in a row', () => {
    const a = generateRequestId();
    const b = generateRequestId();
    expect(a).not.toBe(b);
  });
});
