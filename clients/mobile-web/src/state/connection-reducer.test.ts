import { describe, expect, it } from 'vitest';
import { connectionReducer, initialConnectionState, summarizeConnection } from './connection-reducer';

const capabilities = { version: '0.1', device_name: 'Jarvis PC', features: { text_tasks: true, task_cancel: true, voice: false, image_upload: false, remote_approval: false } };

describe('connectionReducer / summarizeConnection', () => {
  it('starts in a "checking" summary, never claiming online prematurely', () => {
    expect(summarizeConnection(initialConnectionState)).toBe('checking');
  });

  it('reports offline_browser the instant the browser goes offline, regardless of prior state', () => {
    let state = connectionReducer(initialConnectionState, { type: 'capabilities_loaded', capabilities });
    state = connectionReducer(state, { type: 'status_loaded', online: true, state: 'idle' });
    expect(summarizeConnection(state)).toBe('online');

    state = connectionReducer(state, { type: 'browser_online', online: false });
    expect(summarizeConnection(state)).toBe('offline_browser');
  });

  it('reports offline_companion when the browser is online but the device status call fails', () => {
    let state = connectionReducer(initialConnectionState, { type: 'capabilities_loaded', capabilities });
    state = connectionReducer(state, { type: 'status_failed' });
    expect(summarizeConnection(state)).toBe('offline_companion');
  });

  it('reports error when capabilities failed, even if a stale companionOnline flag is true', () => {
    const state = connectionReducer(initialConnectionState, { type: 'capabilities_failed', message: 'boom' });
    expect(summarizeConnection(state)).toBe('error');
  });

  it('only reports online once both capabilities are loaded and status says online', () => {
    let state = connectionReducer(initialConnectionState, { type: 'status_loaded', online: true, state: 'idle' });
    expect(summarizeConnection(state)).toBe('checking'); // capabilities not loaded yet
    state = connectionReducer(state, { type: 'capabilities_loaded', capabilities });
    expect(summarizeConnection(state)).toBe('online');
  });
});
