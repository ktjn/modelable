import { describe, expect, it } from 'vitest';

import {
  initialProviderState,
  providerStateReducer,
  providerStatusLabel,
  type ProviderState,
} from './provider-state';
import type { LlmProvider } from './types';

const fakeProvider: LlmProvider = {
  id: 'test',
  model: 'test-model',
  initialize: async () => {},
  complete: async () => ({ content: '', provider: 'test', model: 'test-model' }),
  dispose: async () => {},
};

describe('providerStateReducer', () => {
  it('starts in idle state', () => {
    expect(initialProviderState.status).toBe('idle');
    expect(initialProviderState.provider).toBeNull();
    expect(initialProviderState.progress).toBe(0);
    expect(initialProviderState.error).toBeNull();
  });

  it('transitions to detecting on detect_start', () => {
    const state = providerStateReducer(initialProviderState, {
      type: 'detect_start',
    });
    expect(state.status).toBe('detecting');
    expect(state.error).toBeNull();
  });

  it('transitions to unsupported on detect_unsupported', () => {
    const detecting: ProviderState = {
      ...initialProviderState,
      status: 'detecting',
    };
    const state = providerStateReducer(detecting, {
      type: 'detect_unsupported',
    });
    expect(state.status).toBe('unsupported');
  });

  it('transitions back to idle on detect_available', () => {
    const detecting: ProviderState = {
      ...initialProviderState,
      status: 'detecting',
    };
    const state = providerStateReducer(detecting, {
      type: 'detect_available',
    });
    expect(state.status).toBe('idle');
  });

  it('transitions to downloading on download_start', () => {
    const state = providerStateReducer(initialProviderState, {
      type: 'download_start',
      provider: fakeProvider,
    });
    expect(state.status).toBe('downloading');
    expect(state.provider).toBe(fakeProvider);
    expect(state.progress).toBe(0);
    expect(state.message).toBe('Starting model download…');
    expect(state.error).toBeNull();
  });

  it('updates progress on download_progress', () => {
    const downloading: ProviderState = {
      ...initialProviderState,
      status: 'downloading',
      provider: fakeProvider,
    };
    const state = providerStateReducer(downloading, {
      type: 'download_progress',
      progress: 0.42,
      message: 'Loading shards…',
    });
    expect(state.progress).toBe(0.42);
    expect(state.message).toBe('Loading shards…');
    expect(state.status).toBe('downloading');
  });

  it('transitions to ready', () => {
    const downloading: ProviderState = {
      ...initialProviderState,
      status: 'downloading',
      provider: fakeProvider,
      progress: 0.9,
    };
    const state = providerStateReducer(downloading, { type: 'ready' });
    expect(state.status).toBe('ready');
    expect(state.progress).toBe(1);
    expect(state.message).toBe('Model ready');
  });

  it('transitions to error', () => {
    const state = providerStateReducer(initialProviderState, {
      type: 'error',
      message: 'WebGPU init failed',
    });
    expect(state.status).toBe('error');
    expect(state.error).toBe('WebGPU init failed');
  });

  it('resets to initial state', () => {
    const errored: ProviderState = {
      ...initialProviderState,
      status: 'error',
      error: 'something broke',
    };
    const state = providerStateReducer(errored, { type: 'reset' });
    expect(state).toEqual(initialProviderState);
  });

  it('clears error on download_start', () => {
    const errored: ProviderState = {
      ...initialProviderState,
      status: 'error',
      error: 'previous error',
    };
    const state = providerStateReducer(errored, {
      type: 'download_start',
      provider: fakeProvider,
    });
    expect(state.error).toBeNull();
    expect(state.status).toBe('downloading');
  });
});

describe('providerStatusLabel', () => {
  it('returns label for idle', () => {
    expect(providerStatusLabel(initialProviderState)).toBe(
      'AI ready to download',
    );
  });

  it('returns label for detecting', () => {
    expect(
      providerStatusLabel({ ...initialProviderState, status: 'detecting' }),
    ).toBe('Detecting WebGPU…');
  });

  it('returns download message for downloading', () => {
    expect(
      providerStatusLabel({
        ...initialProviderState,
        status: 'downloading',
        message: 'Loading 3/5 shards',
      }),
    ).toBe('Loading 3/5 shards');
  });

  it('returns label for ready', () => {
    expect(
      providerStatusLabel({ ...initialProviderState, status: 'ready' }),
    ).toBe('AI model ready');
  });

  it('returns error label with message', () => {
    expect(
      providerStatusLabel({
        ...initialProviderState,
        status: 'error',
        error: 'GPU OOM',
      }),
    ).toBe('AI error: GPU OOM');
  });

  it('returns error label with unknown when error is null', () => {
    expect(
      providerStatusLabel({ ...initialProviderState, status: 'error' }),
    ).toBe('AI error: unknown');
  });

  it('returns label for unsupported', () => {
    expect(
      providerStatusLabel({
        ...initialProviderState,
        status: 'unsupported',
      }),
    ).toBe('WebGPU not available');
  });
});
