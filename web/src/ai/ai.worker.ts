import type { LlmRequest } from './types';

export type AiWorkerRequest =
  | { type: 'initialize'; model: string }
  | { type: 'complete'; id: string; request: LlmRequest }
  | { type: 'dispose' };

export type AiWorkerResponse =
  | { type: 'progress'; progress: number; message: string }
  | { type: 'initialized' }
  | { type: 'completed'; id: string; content: string; promptTokens?: number; completionTokens?: number }
  | { type: 'error'; id?: string; message: string };

const ctx = globalThis as unknown as Worker;

let engine: import('@mlc-ai/web-llm').MLCEngine | null = null;
let currentModel: string | null = null;

ctx.addEventListener('message', (event: MessageEvent<AiWorkerRequest>) => {
  const msg = event.data;
  if (msg.type === 'initialize') {
    void handleInitialize(msg.model);
  } else if (msg.type === 'complete') {
    void handleComplete(msg.id, msg.request);
  } else if (msg.type === 'dispose') {
    void handleDispose();
  }
});

async function handleInitialize(model: string): Promise<void> {
  try {
    const { MLCEngine } = await import('@mlc-ai/web-llm');
    engine = new MLCEngine({
      initProgressCallback: (report) => {
        const response: AiWorkerResponse = {
          type: 'progress',
          progress: report.progress,
          message: report.text,
        };
        ctx.postMessage(response);
      },
    });
    await engine.reload(model);
    currentModel = model;
    const response: AiWorkerResponse = { type: 'initialized' };
    ctx.postMessage(response);
  } catch (error: unknown) {
    const response: AiWorkerResponse = {
      type: 'error',
      message: error instanceof Error ? error.message : 'Failed to initialize model',
    };
    ctx.postMessage(response);
  }
}

async function handleComplete(id: string, request: LlmRequest): Promise<void> {
  if (engine === null || currentModel === null) {
    const response: AiWorkerResponse = {
      type: 'error',
      id,
      message: 'Model not initialized',
    };
    ctx.postMessage(response);
    return;
  }

  try {
    const reply = await engine.chat.completions.create({
      messages: [
        { role: 'system', content: request.system },
        { role: 'user', content: request.user },
      ],
      temperature: request.temperature,
      response_format: request.responseFormat === 'json'
        ? { type: 'json_object' }
        : undefined,
    });

    const content = reply.choices[0]?.message?.content ?? '';
    const usage = reply.usage;
    const response: AiWorkerResponse = {
      type: 'completed',
      id,
      content,
      promptTokens: usage?.prompt_tokens,
      completionTokens: usage?.completion_tokens,
    };
    ctx.postMessage(response);
  } catch (error: unknown) {
    const response: AiWorkerResponse = {
      type: 'error',
      id,
      message: error instanceof Error ? error.message : 'Completion failed',
    };
    ctx.postMessage(response);
  }
}

async function handleDispose(): Promise<void> {
  if (engine !== null) {
    await engine.unload();
    engine = null;
    currentModel = null;
  }
}
