import type { LlmRequest } from './types';

export type AiWorkerRequest =
  | { type: 'initialize'; model: string; completionParams?: Record<string, unknown> }
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
let completionParams: Record<string, unknown> | null = null;

ctx.addEventListener('message', (event: MessageEvent<AiWorkerRequest>) => {
  const msg = event.data;
  if (msg.type === 'initialize') {
    void handleInitialize(msg.model, msg.completionParams);
  } else if (msg.type === 'complete') {
    void handleComplete(msg.id, msg.request);
  } else if (msg.type === 'dispose') {
    void handleDispose();
  }
});

async function handleInitialize(
  model: string,
  extraParams?: Record<string, unknown>,
): Promise<void> {
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
    await engine.reload(model, {
      context_window_size: 32768,
    });
    currentModel = model;
    completionParams = extraParams ?? null;
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
    const reply = await engine.chat.completions.create(
      createWebLlmCompletionRequest(request, completionParams ?? undefined),
    );

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

export function createWebLlmCompletionRequest(
  request: LlmRequest,
  extraParams?: Record<string, unknown>,
) {
  return {
    messages: [
      { role: 'system' as const, content: request.system },
      { role: 'user' as const, content: request.user },
    ],
    temperature: request.temperature,
    ...extraParams,
    response_format: request.responseFormat === 'json'
      ? request.schema === undefined
        ? { type: 'json_object' as const }
        : { type: 'json_object' as const, schema: JSON.stringify(request.schema) }
      : undefined,
  };
}

async function handleDispose(): Promise<void> {
  if (engine !== null) {
    await engine.unload();
    engine = null;
    currentModel = null;
    completionParams = null;
  }
}
