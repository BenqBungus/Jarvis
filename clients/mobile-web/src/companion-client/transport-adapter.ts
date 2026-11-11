import type { CompanionClient, SubmitTaskInput } from './client';
import type {
  ApiErrorBody,
  CancelResponse,
  CapabilitiesResponse,
  StatusResponse,
  SubmitTaskResponse,
  TaskResource,
} from '../contract/types';
import { CompanionApiError, CompanionNetworkError, CompanionTimeoutError } from './errors';

const REQUEST_TIMEOUT_MS = 10_000;

export interface TransportConfig {
  /** e.g. https://jarvis-pc.example: never hardcoded, read from
   * VITE_COMPANION_BASE_URL. Combined with the contract's own "/v1" base
   * path. */
  baseUrl: string;
  /** Paired-device bearer token. Sent only as an Authorization header --
   * never in a query string or logged. There is no real pairing protocol
   * yet (contract: "transport details pending"), so this is a placeholder
   * until one exists; see clients/CONTRACT_REQUESTS.md. */
  token: string;
}

/**
 * Real adapter, written to the exact contract shape. There is no companion
 * server yet, so every call here will fail with CompanionNetworkError today
 * -- that is expected and correct, not a bug to "fix" by inventing a
 * fallback. Wiring this up to a real server later should require no changes
 * to this file's public behavior, only a real baseUrl/token.
 */
export class TransportCompanionAdapter implements CompanionClient {
  readonly mode = 'transport' as const;

  constructor(private readonly config: TransportConfig) {}

  async getCapabilities(signal?: AbortSignal): Promise<CapabilitiesResponse> {
    return this.request<CapabilitiesResponse>('GET', '/v1/capabilities', undefined, signal);
  }

  async getStatus(signal?: AbortSignal): Promise<StatusResponse> {
    return this.request<StatusResponse>('GET', '/v1/status', undefined, signal);
  }

  async submitTask(input: SubmitTaskInput, signal?: AbortSignal): Promise<SubmitTaskResponse> {
    return this.request<SubmitTaskResponse>(
      'POST',
      '/v1/tasks',
      { request_id: input.requestId, text: input.text, project_id: input.projectId ?? null },
      signal,
    );
  }

  async getTask(taskId: string, signal?: AbortSignal): Promise<TaskResource> {
    return this.request<TaskResource>('GET', `/v1/tasks/${encodeURIComponent(taskId)}`, undefined, signal);
  }

  async cancelTask(taskId: string, signal?: AbortSignal): Promise<CancelResponse> {
    return this.request<CancelResponse>('POST', `/v1/tasks/${encodeURIComponent(taskId)}/cancel`, undefined, signal);
  }

  private async request<T>(method: 'GET' | 'POST', path: string, body: unknown, callerSignal?: AbortSignal): Promise<T> {
    const url = new URL(path, this.config.baseUrl).toString();
    const timeoutController = new AbortController();
    const timeout = setTimeout(() => timeoutController.abort(), REQUEST_TIMEOUT_MS);
    const signal = combineSignals(callerSignal, timeoutController.signal);

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        // Never cache an API response -- this is the transport-level half
        // of the "never cache /v1/*" requirement; the service worker's
        // NetworkOnly rule is the other half.
        cache: 'no-store',
        signal,
        headers: {
          // Bearer token as a header, never a query string.
          Authorization: `Bearer ${this.config.token}`,
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (cause) {
      clearTimeout(timeout);
      if (timeoutController.signal.aborted && !callerSignal?.aborted) {
        throw new CompanionTimeoutError();
      }
      throw new CompanionNetworkError('Could not reach the companion server.', cause);
    }
    clearTimeout(timeout);

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (cause) {
      throw new CompanionNetworkError('Companion server returned a non-JSON response.', cause);
    }

    if (!response.ok) {
      const errorBody = extractErrorBody(payload, response.status);
      throw new CompanionApiError(errorBody);
    }

    return payload as T;
  }
}

function extractErrorBody(payload: unknown, status: number): ApiErrorBody {
  if (
    payload &&
    typeof payload === 'object' &&
    'error' in payload &&
    payload.error &&
    typeof payload.error === 'object'
  ) {
    const error = payload.error as Partial<ApiErrorBody>;
    return {
      code: error.code ?? `http_${status}`,
      message: error.message ?? `Request failed with status ${status}.`,
      retryable: error.retryable ?? status >= 500,
    };
  }
  return { code: `http_${status}`, message: `Request failed with status ${status}.`, retryable: status >= 500 };
}

function combineSignals(a?: AbortSignal, b?: AbortSignal): AbortSignal | undefined {
  if (!a) return b;
  if (!b) return a;
  if (typeof AbortSignal.any === 'function') return AbortSignal.any([a, b]);
  // Fallback for engines without AbortSignal.any: propagate whichever fires first.
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  a.addEventListener('abort', onAbort);
  b.addEventListener('abort', onAbort);
  return controller.signal;
}
