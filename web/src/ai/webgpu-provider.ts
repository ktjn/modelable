import type { AiWorkerRequest, AiWorkerResponse } from './ai.worker';
import type { LlmProvider, LlmRequest, LlmResponse } from './types';

export interface ModelOption {
  id: string;
  label: string;
  description: string;
  /** Minimum GPU VRAM required in MB. */
  vramMb: number;
  /** Required storage buffer size in bytes. */
  bufferSizeRequiredBytes?: number;
  /** Extra params merged into every completion request (e.g. `extra_body`). */
  completionParams?: Record<string, unknown>;
  /** Whether the model is recommended for the current system. */
  recommended?: boolean;
}

export const DEFAULT_MODELS: ModelOption[] = [
  {
    id: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC',
    label: 'Qwen 2.5 0.5B',
    description: '~945 MB VRAM',
    vramMb: 945,
  },
  {
    id: 'Qwen3-1.7B-q4f16_1-MLC',
    label: 'Qwen 3 1.7B',
    description: '~2 GB VRAM',
    vramMb: 2037,
    completionParams: { extra_body: { enable_thinking: false } },
  },
];

export function createModelOption(id: string): ModelOption {
  return {
    id,
    label: id,
    description: 'Dynamic model',
    vramMb: 0, // Unknown
  };
}

export function detectWebGpu(): boolean {
  return typeof navigator !== 'undefined' && 'gpu' in navigator;
}

/** Fetches GPU adapter limits if available. */
export async function getGpuLimits(): Promise<GPUSupportedLimits | null> {
  if (!detectWebGpu()) return null;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    return adapter?.limits ?? null;
  } catch {
    return null;
  }
}

/** Suggests a model based on GPU limits. */
export function suggestModel(
  models: ModelOption[],
  limits: GPUSupportedLimits | null,
): string {
  if (limits === null) {
    // Default to a small model if no limits found
    return 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC';
  }

  const maxStorageBuffer = limits.maxStorageBufferBindingSize;

  const filtered = models.filter((m) => {
    if (m.bufferSizeRequiredBytes !== undefined) {
      return m.bufferSizeRequiredBytes <= maxStorageBuffer;
    }
    // Fallback heuristic if bufferSizeRequiredBytes is missing
    if (m.vramMb > 0) {
      const estimatedBufferReq = m.vramMb * 1024 * 1024;
      return estimatedBufferReq <= maxStorageBuffer;
    }
    return true;
  });

  if (filtered.length === 0) return 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC';

  // Prefer models with more VRAM if they fit
  const sorted = [...filtered].sort((a, b) => b.vramMb - a.vramMb);
  return sorted[0]!.id;
}

export class WebGpuProvider implements LlmProvider {
  readonly id = 'webgpu';
  readonly model: string;
  readonly completionParams: Record<string, unknown> | null;
  private worker: Worker | null = null;
  private pendingCompletions = new Map<
    string,
    { resolve: (response: LlmResponse) => void; reject: (error: Error) => void }
  >();
  private nextId = 0;

  static async getWebLlmModels(): Promise<ModelOption[]> {
    const worker = new Worker(
      new URL('./ai.worker.ts', import.meta.url),
      { type: 'module' },
    );

    return new Promise<ModelOption[]>((resolve, reject) => {
      const handler = (event: MessageEvent<AiWorkerResponse>): void => {
        const msg = event.data;
        if (msg.type === 'models') {
          worker.removeEventListener('message', handler);
          worker.terminate();
          resolve(msg.models);
        } else if (msg.type === 'error') {
          worker.removeEventListener('message', handler);
          worker.terminate();
          reject(new Error(msg.message));
        }
      };
      worker.addEventListener('message', handler);
      worker.postMessage({ type: 'list_models' });
    });
  }

  constructor(modelConfig?: ModelOption) {
    this.model = modelConfig?.id ?? DEFAULT_MODELS[0]!.id;
    this.completionParams = modelConfig?.completionParams ?? null;
  }

  async initialize(
    onProgress?: (progress: number, message: string) => void,
  ): Promise<void> {
    if (!detectWebGpu()) {
      throw new Error('WebGPU is not available in this browser');
    }

    this.worker = new Worker(
      new URL('./ai.worker.ts', import.meta.url),
      { type: 'module' },
    );

    return new Promise<void>((resolve, reject) => {
      const worker = this.worker!;
      const handler = (event: MessageEvent<AiWorkerResponse>): void => {
        const msg = event.data;
        if (msg.type === 'progress') {
          onProgress?.(msg.progress, msg.message);
        } else if (msg.type === 'initialized') {
          worker.removeEventListener('message', handler);
          worker.addEventListener('message', this.handleWorkerMessage);
          resolve();
        } else if (msg.type === 'error') {
          worker.removeEventListener('message', handler);
          reject(new Error(msg.message));
        }
      };
      worker.addEventListener('message', handler);
      const request: AiWorkerRequest = {
        type: 'initialize',
        model: this.model,
        completionParams: this.completionParams ?? undefined,
      };
      worker.postMessage(request);
    });
  }

  async complete(request: LlmRequest): Promise<LlmResponse> {
    if (this.worker === null) {
      throw new Error('Provider not initialized');
    }

    const id = String(this.nextId++);
    return new Promise<LlmResponse>((resolve, reject) => {
      this.pendingCompletions.set(id, { resolve, reject });
      const msg: AiWorkerRequest = { type: 'complete', id, request };
      this.worker!.postMessage(msg);
    });
  }

  async dispose(): Promise<void> {
    if (this.worker !== null) {
      const msg: AiWorkerRequest = { type: 'dispose' };
      this.worker.postMessage(msg);
      this.worker.terminate();
      this.worker = null;
    }
    for (const [, pending] of this.pendingCompletions) {
      pending.reject(new Error('Provider disposed'));
    }
    this.pendingCompletions.clear();
  }

  private handleWorkerMessage = (event: MessageEvent<AiWorkerResponse>): void => {
    const msg = event.data;
    if (msg.type === 'completed') {
      const pending = this.pendingCompletions.get(msg.id);
      if (pending !== undefined) {
        this.pendingCompletions.delete(msg.id);
        pending.resolve({
          content: msg.content,
          provider: this.id,
          model: this.model,
          promptTokens: msg.promptTokens,
          completionTokens: msg.completionTokens,
        });
      }
    } else if (msg.type === 'error' && msg.id !== undefined) {
      const pending = this.pendingCompletions.get(msg.id);
      if (pending !== undefined) {
        this.pendingCompletions.delete(msg.id);
        pending.reject(new Error(msg.message));
      }
    }
  };
}
