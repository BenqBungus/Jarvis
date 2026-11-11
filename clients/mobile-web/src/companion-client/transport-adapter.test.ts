import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TransportCompanionAdapter } from './transport-adapter';
import { CompanionApiError, CompanionNetworkError } from './errors';

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init });
}

describe('TransportCompanionAdapter', () => {
  const config = { baseUrl: 'https://jarvis-pc.example', token: 'super-secret-token' };
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reports mode "transport"', () => {
    expect(new TransportCompanionAdapter(config).mode).toBe('transport');
  });

  it('sends the bearer token as an Authorization header, never in the URL', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ version: '0.1', device_name: 'x', features: {} }));
    const adapter = new TransportCompanionAdapter(config);
    await adapter.getCapabilities();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain('super-secret-token');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer super-secret-token');
  });

  it('never lets a request be served from cache', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ online: true, state: 'idle', active_task_id: null }));
    const adapter = new TransportCompanionAdapter(config);
    await adapter.getStatus();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.cache).toBe('no-store');
  });

  it('maps a fetch rejection to CompanionNetworkError, not an uncaught throw', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const adapter = new TransportCompanionAdapter(config);
    await expect(adapter.getStatus()).rejects.toBeInstanceOf(CompanionNetworkError);
  });

  it('maps a contract-shaped error response to CompanionApiError with the same code/message/retryable', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: 'desktop_approval_required', message: 'Approve on the desktop.', retryable: false } }, { status: 409 }),
    );
    const adapter = new TransportCompanionAdapter(config);
    await expect(adapter.submitTask({ requestId: 'r1', text: 'do a thing' })).rejects.toMatchObject({
      code: 'desktop_approval_required',
      message: 'Approve on the desktop.',
      retryable: false,
    });
  });

  it('falls back to a synthesized error for a non-contract-shaped error body', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ oops: true }, { status: 500 }));
    const adapter = new TransportCompanionAdapter(config);
    let caught: unknown;
    try {
      await adapter.getStatus();
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(CompanionApiError);
    expect((caught as CompanionApiError).retryable).toBe(true); // 5xx defaults retryable
  });

  it('builds the task endpoints under the contract\'s /v1 base path', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ task_id: 't1', state: 'running', summary: null, result: null, error: null, revision: 1 }));
    const adapter = new TransportCompanionAdapter(config);
    await adapter.getTask('t1');
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe('https://jarvis-pc.example/v1/tasks/t1');
  });

  it('POSTs cancel to the exact contract path', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ task_id: 't1', cancel_requested: true }));
    const adapter = new TransportCompanionAdapter(config);
    await adapter.cancelTask('t1');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://jarvis-pc.example/v1/tasks/t1/cancel');
    expect(init.method).toBe('POST');
  });
});
