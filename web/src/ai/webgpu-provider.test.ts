import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { detectWebGpu, WebGpuProvider } from './webgpu-provider';

describe('detectWebGpu', () => {
  const originalNavigator = globalThis.navigator;

  afterEach(() => {
    Object.defineProperty(globalThis, 'navigator', {
      value: originalNavigator,
      configurable: true,
    });
  });

  it('returns false when navigator is undefined', () => {
    Object.defineProperty(globalThis, 'navigator', {
      value: undefined,
      configurable: true,
    });
    expect(detectWebGpu()).toBe(false);
  });

  it('returns false when gpu is not in navigator', () => {
    Object.defineProperty(globalThis, 'navigator', {
      value: {},
      configurable: true,
    });
    expect(detectWebGpu()).toBe(false);
  });

  it('returns true when gpu is in navigator', () => {
    Object.defineProperty(globalThis, 'navigator', {
      value: { gpu: {} },
      configurable: true,
    });
    expect(detectWebGpu()).toBe(true);
  });
});

function firstHandler(
  mockWorker: { listeners: Map<string, ((event: { data: unknown }) => void)[]> },
  event: string,
): (event: { data: unknown }) => void {
  const handlers = mockWorker.listeners.get(event) ?? [];
  const handler = handlers[0];
  if (handler === undefined) {
    throw new Error(`No handler registered for "${event}"`);
  }
  return handler;
}

function lastHandler(
  mockWorker: { listeners: Map<string, ((event: { data: unknown }) => void)[]> },
  event: string,
): (event: { data: unknown }) => void {
  const handlers = mockWorker.listeners.get(event) ?? [];
  const handler = handlers[handlers.length - 1];
  if (handler === undefined) {
    throw new Error(`No handler registered for "${event}"`);
  }
  return handler;
}

describe('WebGpuProvider', () => {
  let mockWorker: {
    postMessage: ReturnType<typeof vi.fn>;
    addEventListener: ReturnType<typeof vi.fn>;
    removeEventListener: ReturnType<typeof vi.fn>;
    terminate: ReturnType<typeof vi.fn>;
    listeners: Map<string, ((event: { data: unknown }) => void)[]>;
  };

  beforeEach(() => {
    mockWorker = {
      postMessage: vi.fn(),
      addEventListener: vi.fn((event: string, handler: (event: { data: unknown }) => void) => {
        const handlers = mockWorker.listeners.get(event) ?? [];
        handlers.push(handler);
        mockWorker.listeners.set(event, handlers);
      }),
      removeEventListener: vi.fn((event: string, handler: (event: { data: unknown }) => void) => {
        const handlers = mockWorker.listeners.get(event) ?? [];
        mockWorker.listeners.set(
          event,
          handlers.filter((h) => h !== handler),
        );
      }),
      terminate: vi.fn(),
      listeners: new Map(),
    };

    vi.stubGlobal('Worker', class {
      constructor() {
        return mockWorker as unknown as Worker;
      }
    });

    Object.defineProperty(globalThis, 'navigator', {
      value: { gpu: {} },
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses default model when none specified', () => {
    const provider = new WebGpuProvider();
    expect(provider.model).toBe('Qwen2.5-0.5B-Instruct-q4f16_1-MLC');
    expect(provider.id).toBe('webgpu');
  });

  it('accepts custom model', () => {
    const provider = new WebGpuProvider('custom-model');
    expect(provider.model).toBe('custom-model');
  });

  it('initialize sends initialize message and resolves on initialized', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();

    expect(mockWorker.listeners.get('message')?.length).toBe(1);
    expect(mockWorker.postMessage).toHaveBeenCalledWith({
      type: 'initialize',
      model: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC',
    });

    firstHandler(mockWorker, 'message')({ data: { type: 'initialized' } });
    await expect(initPromise).resolves.toBeUndefined();
  });

  it('initialize calls onProgress during download', async () => {
    const provider = new WebGpuProvider();
    const onProgress = vi.fn();
    const initPromise = provider.initialize(onProgress);

    firstHandler(mockWorker, 'message')({
      data: { type: 'progress', progress: 0.5, message: 'Loading…' },
    });
    expect(onProgress).toHaveBeenCalledWith(0.5, 'Loading…');

    firstHandler(mockWorker, 'message')({ data: { type: 'initialized' } });
    await initPromise;
  });

  it('initialize rejects on error', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();

    firstHandler(mockWorker, 'message')({
      data: { type: 'error', message: 'WebGPU not supported' },
    });

    await expect(initPromise).rejects.toThrow('WebGPU not supported');
  });

  it('initialize throws when WebGPU is not available', async () => {
    Object.defineProperty(globalThis, 'navigator', {
      value: {},
      configurable: true,
    });
    const provider = new WebGpuProvider();
    await expect(provider.initialize()).rejects.toThrow(
      'WebGPU is not available',
    );
  });

  it('complete sends message and resolves with response', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();
    firstHandler(mockWorker, 'message')({ data: { type: 'initialized' } });
    await initPromise;

    const request = {
      system: 'You are helpful',
      user: 'Hello',
      temperature: 0.7,
      responseFormat: 'text' as const,
    };
    const completePromise = provider.complete(request);

    expect(mockWorker.postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: 'complete',
        id: '0',
        request,
      }),
    );

    lastHandler(mockWorker, 'message')({
      data: {
        type: 'completed',
        id: '0',
        content: 'Hi there!',
        promptTokens: 10,
        completionTokens: 5,
      },
    });

    const response = await completePromise;
    expect(response.content).toBe('Hi there!');
    expect(response.provider).toBe('webgpu');
    expect(response.model).toBe('Qwen2.5-0.5B-Instruct-q4f16_1-MLC');
    expect(response.promptTokens).toBe(10);
    expect(response.completionTokens).toBe(5);
  });

  it('complete rejects when not initialized', async () => {
    const provider = new WebGpuProvider();
    await expect(
      provider.complete({
        system: '',
        user: '',
        temperature: 0,
        responseFormat: 'text',
      }),
    ).rejects.toThrow('Provider not initialized');
  });

  it('dispose terminates worker and rejects pending completions', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();
    firstHandler(mockWorker, 'message')({ data: { type: 'initialized' } });
    await initPromise;

    const completePromise = provider.complete({
      system: '',
      user: 'test',
      temperature: 0,
      responseFormat: 'text',
    });

    await provider.dispose();

    expect(mockWorker.postMessage).toHaveBeenCalledWith({ type: 'dispose' });
    expect(mockWorker.terminate).toHaveBeenCalled();
    await expect(completePromise).rejects.toThrow('Provider disposed');
  });
});
