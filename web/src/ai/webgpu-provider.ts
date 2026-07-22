import type { AiWorkerRequest, AiWorkerResponse } from './ai.worker';
import type { LlmProvider, LlmRequest, LlmResponse } from './types';

const DEFAULT_MODEL = 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC';

export function detectWebGpu(): boolean {
  return typeof navigator !== 'undefined' && 'gpu' in navigator;
}

export class WebGpuProvider implements LlmProvider {
  readonly id = 'webgpu';
  readonly model: string;
  private worker: Worker | null = null;
  private pendingCompletions = new Map<
    string,
    { resolve: (response: LlmResponse) => void; reject: (error: Error) => void }
  >();
  private nextId = 0;

  constructor(model?: string) {
    this.model = model ?? DEFAULT_MODEL;
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
      const request: AiWorkerRequest = { type: 'initialize', model: this.model };
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
