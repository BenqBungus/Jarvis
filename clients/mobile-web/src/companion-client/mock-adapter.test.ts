import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockCompanionAdapter } from './mock-adapter';
import { CompanionApiError, CompanionNetworkError } from './errors';

describe('MockCompanionAdapter', () => {
  let adapter: MockCompanionAdapter;

  beforeEach(() => {
    vi.useFakeTimers();
    adapter = new MockCompanionAdapter();
  });

  afterEach(() => {
    adapter.disposeForTests();
    vi.useRealTimers();
  });

  it('reports mode "mock" and today\'s real contract feature flags (voice/image_upload off)', async () => {
    expect(adapter.mode).toBe('mock');
    const capabilities = await adapter.getCapabilities();
    expect(capabilities.features.voice).toBe(false);
    expect(capabilities.features.image_upload).toBe(false);
    expect(capabilities.features.text_tasks).toBe(true);
  });

  it('never returns a fixture value shaped like real system telemetry', async () => {
    const { task_id } = await adapter.submitTask({ requestId: 'r1', text: 'default task' });
    await vi.advanceTimersByTimeAsync(3200);
    const resource = await adapter.getTask(task_id);
    expect(resource.state).toBe('completed');
    const resultText = String(resource.result);
    expect(resultText).toMatch(/mock/i);
    expect(resultText).not.toMatch(/°?c\b/i); // no "47C"/"47°C"-style temperature
    expect(resultText).not.toMatch(/\d+%/); // no fabricated percentage
  });

  it('runs the default lifecycle: queued -> running -> completed', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'do something ordinary' });
    expect(submitted.state).toBe('queued');

    let resource = await adapter.getTask(submitted.task_id);
    expect(resource.state).toBe('queued');

    await vi.advanceTimersByTimeAsync(700);
    resource = await adapter.getTask(submitted.task_id);
    expect(resource.state).toBe('running');

    await vi.advanceTimersByTimeAsync(2600);
    resource = await adapter.getTask(submitted.task_id);
    expect(resource.state).toBe('completed');
    expect(resource.result).toBeTruthy();
  });

  it('sticks at awaiting_desktop_approval for the "approve" scenario', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'please approve this' });
    await vi.advanceTimersByTimeAsync(3200);
    const resource = await adapter.getTask(submitted.task_id);
    expect(resource.state).toBe('awaiting_desktop_approval');
  });

  it('reaches failed with a retryable error for the "fail" scenario', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'this should fail' });
    await vi.advanceTimersByTimeAsync(3200);
    const resource = await adapter.getTask(submitted.task_id);
    expect(resource.state).toBe('failed');
    expect(resource.error?.code).toBe('mock_failure');
    expect(resource.error?.retryable).toBe(true);
  });

  it('throws once then recovers for the "flaky" scenario', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'flaky please' });
    await expect(adapter.getTask(submitted.task_id)).rejects.toBeInstanceOf(CompanionNetworkError);
    const resource = await adapter.getTask(submitted.task_id);
    expect(resource.state).toBe('queued');
  });

  it('is idempotent per request_id: resubmitting the same request_id returns the existing task', async () => {
    const first = await adapter.submitTask({ requestId: 'same-id', text: 'default task' });
    const second = await adapter.submitTask({ requestId: 'same-id', text: 'default task' });
    expect(second.task_id).toBe(first.task_id);
  });

  it('bumps revision on every state transition so backoff can detect change', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'do something ordinary' });
    const first = await adapter.getTask(submitted.task_id);
    await vi.advanceTimersByTimeAsync(700);
    const second = await adapter.getTask(submitted.task_id);
    expect(second.revision).toBeGreaterThan(first.revision);
  });

  it('cancel is cooperative, not instant: state flips to cancelled only on the next tick', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'do something ordinary' });
    const cancelResponse = await adapter.cancelTask(submitted.task_id);
    expect(cancelResponse.cancel_requested).toBe(true);

    const immediately = await adapter.getTask(submitted.task_id);
    expect(immediately.state).not.toBe('cancelled');

    await vi.advanceTimersByTimeAsync(500);
    const afterDelay = await adapter.getTask(submitted.task_id);
    expect(afterDelay.state).toBe('cancelled');
  });

  it('cancelling an already-terminal task is a harmless no-op, not an error', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'do something ordinary' });
    await vi.advanceTimersByTimeAsync(3200);
    const beforeCancel = await adapter.getTask(submitted.task_id);
    expect(beforeCancel.state).toBe('completed');

    const cancelResponse = await adapter.cancelTask(submitted.task_id);
    expect(cancelResponse.cancel_requested).toBe(true);

    const afterCancel = await adapter.getTask(submitted.task_id);
    expect(afterCancel.state).toBe('completed'); // unchanged, "does not undo completed actions"
  });

  it('rejects an unknown task_id with a non-retryable CompanionApiError', async () => {
    await expect(adapter.getTask('does-not-exist')).rejects.toBeInstanceOf(CompanionApiError);
  });

  it('status reflects an active task and clears once it resolves', async () => {
    const submitted = await adapter.submitTask({ requestId: 'r1', text: 'do something ordinary' });
    let status = await adapter.getStatus();
    expect(status.active_task_id).toBe(submitted.task_id);

    await vi.advanceTimersByTimeAsync(3200);
    await adapter.getTask(submitted.task_id); // let the completed transition settle bookkeeping
    status = await adapter.getStatus();
    expect(status.active_task_id).toBeNull();
  });
});
