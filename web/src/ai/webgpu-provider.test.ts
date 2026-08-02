import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { detectWebGpu, suggestModels, WebGpuProvider, type ModelOption } from './webgpu-provider';

function model(id: string, vramMb: number): ModelOption {
  return { id, label: id, description: '', vramMb };
}

describe('suggestModels', () => {
  it('returns only fast fallback id when limits are null', () => {
    const models = [model('a', 500), model('b', 2000)];
    expect(suggestModels(models, null)).toEqual({
      fast: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC',
    });
  });

  it('returns empty object when no models fit', () => {
    const models = [model('a', 999999)];
    const limits = { maxStorageBufferBindingSize: 1 } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({});
  });

  it('assigns the single fitting model to fast only', () => {
    const models = [model('a', 500)];
    const limits = {
      maxStorageBufferBindingSize: 500 * 1024 * 1024,
    } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({ fast: 'a' });
  });

  it('assigns two fitting models to fast and quality', () => {
    const models = [model('small', 500), model('large', 2000)];
    const limits = {
      maxStorageBufferBindingSize: 2000 * 1024 * 1024,
    } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({
      fast: 'small',
      quality: 'large',
    });
  });

  it('assigns three or more fitting models to fast, balanced, and quality by VRAM position', () => {
    const models = [
      model('tiny', 500),
      model('mid', 2000),
      model('big', 8000),
    ];
    const limits = {
      maxStorageBufferBindingSize: 8000 * 1024 * 1024,
    } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({
      fast: 'tiny',
      balanced: 'mid',
      quality: 'big',
    });
  });

  it('picks the fitting model closest to the VRAM midpoint as balanced among many candidates', () => {
    const models = [
      model('tiny', 500),
      model('close-to-mid', 4200),
      model('far-from-mid', 6000),
      model('big', 8000),
    ];
    const limits = {
      maxStorageBufferBindingSize: 8000 * 1024 * 1024,
    } as GPUSupportedLimits;
    // midpoint of [500, 8000] is 4250; 4200 is closer to 4250 than 6000 is.
    expect(suggestModels(models, limits)).toEqual({
      fast: 'tiny',
      balanced: 'close-to-mid',
      quality: 'big',
    });
  });
});

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
    const provider = new WebGpuProvider({ id: 'custom-model', label: 'Custom', description: '', vramMb: 0 });
    expect(provider.model).toBe('custom-model');
  });

  it('initialize sends initialize message and resolves on initialized', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();

    expect(mockWorker.listeners.get('message')?.length).toBe(1);
    expect(mockWorker.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'initialize',
        model: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC',
      }),
    );

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

  it('initialize rejects with AiProviderError using worker code when provided', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();

    firstHandler(mockWorker, 'message')({
      data: { type: 'error', message: 'Model too large', code: 'INITIALIZATION_FAILED' },
    });

    await expect(initPromise).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'INITIALIZATION_FAILED',
      message: 'Model too large',
    });
  });

  it('initialize rejects with AiProviderError defaulting to INITIALIZATION_FAILED when worker omits code', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();

    firstHandler(mockWorker, 'message')({
      data: { type: 'error', message: 'WebGPU not supported' },
    });

    await expect(initPromise).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'INITIALIZATION_FAILED',
    });
  });

  it('initialize throws AiProviderError with WEBGPU_UNSUPPORTED when WebGPU is not available', async () => {
    Object.defineProperty(globalThis, 'navigator', {
      value: {},
      configurable: true,
    });
    const provider = new WebGpuProvider();
    await expect(provider.initialize()).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'WEBGPU_UNSUPPORTED',
    });
  });

  it('getWebLlmModels rejects with AiProviderError coded MODEL_LIST_FAILED', async () => {
    const promise = WebGpuProvider.getWebLlmModels();
    firstHandler(mockWorker, 'message')({
      data: { type: 'error', message: 'fetch failed' },
    });
    await expect(promise).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'MODEL_LIST_FAILED',
      message: 'fetch failed',
    });
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
    ).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'COMPLETION_FAILED',
      message: 'Provider not initialized',
    });
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
