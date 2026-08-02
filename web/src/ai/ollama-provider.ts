import type { LlmProvider, LlmRequest, LlmResponse } from './types';

/**
 * Ollama's default local server address. The Playground only talks to this
 * exact origin (not a user-configurable base URL) because the page's CSP
 * `connect-src` must allowlist origins statically -- widening it to arbitrary
 * user input would let any visitor's browser probe arbitrary localhost ports
 * from this page.
 */
export const OLLAMA_DEFAULT_BASE_URL = 'http://localhost:11434';

export type OllamaProviderErrorCode =
  | 'CONNECTION_FAILED'
  | 'MODEL_LIST_FAILED'
  | 'MODEL_NOT_INSTALLED'
  | 'COMPLETION_FAILED';

export class OllamaProviderError extends Error {
  constructor(
    readonly code: OllamaProviderErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'OllamaProviderError';
  }
}

function connectionFailedError(baseUrl: string): OllamaProviderError {
  return new OllamaProviderError(
    'CONNECTION_FAILED',
    `Could not reach Ollama at ${baseUrl}. Make sure "ollama serve" is running, and that ` +
      `OLLAMA_ORIGINS includes this page's origin (Ollama rejects cross-origin requests by default).`,
  );
}

interface OllamaTagsResponse {
  models?: unknown;
}

/** Probes a local Ollama server's installed models via `GET /api/tags`. */
export async function listOllamaModels(
  baseUrl: string = OLLAMA_DEFAULT_BASE_URL,
): Promise<string[]> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, '')}/api/tags`, {
      method: 'GET',
    });
  } catch {
    throw connectionFailedError(baseUrl);
  }

  if (!response.ok) {
    throw new OllamaProviderError(
      'MODEL_LIST_FAILED',
      `Ollama returned ${response.status} ${response.statusText}`,
    );
  }

  let payload: OllamaTagsResponse;
  try {
    payload = (await response.json()) as OllamaTagsResponse;
  } catch {
    throw new OllamaProviderError('MODEL_LIST_FAILED', 'Ollama returned invalid JSON');
  }

  if (!Array.isArray(payload.models)) return [];
  const names: string[] = [];
  for (const entry of payload.models) {
    if (
      entry !== null &&
      typeof entry === 'object' &&
      typeof (entry as { name?: unknown }).name === 'string'
    ) {
      names.push((entry as { name: string }).name);
    }
  }
  return names.sort();
}

interface OllamaChatResponse {
  message?: { content?: unknown };
  prompt_eval_count?: unknown;
  eval_count?: unknown;
}

function numberOrUndefined(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined;
}

export class OllamaProvider implements LlmProvider {
  readonly id = 'ollama';
  readonly model: string;
  private readonly baseUrl: string;

  constructor(model: string, baseUrl: string = OLLAMA_DEFAULT_BASE_URL) {
    this.model = model;
    this.baseUrl = baseUrl;
  }

  /** No download step -- verifies the server is reachable and the model is installed. */
  async initialize(): Promise<void> {
    const models = await listOllamaModels(this.baseUrl);
    if (!models.includes(this.model)) {
      throw new OllamaProviderError(
        'MODEL_NOT_INSTALLED',
        `Model "${this.model}" is not installed on the Ollama server. Run "ollama pull ${this.model}".`,
      );
    }
  }

  async complete(request: LlmRequest): Promise<LlmResponse> {
    const payload: Record<string, unknown> = {
      model: this.model,
      messages: [
        { role: 'system', content: request.system },
        { role: 'user', content: request.user },
      ],
      stream: false,
      options: { temperature: request.temperature },
    };
    if (request.schema !== undefined) {
      payload.format = request.schema;
    } else if (request.responseFormat === 'json') {
      payload.format = 'json';
    }

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl.replace(/\/$/, '')}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      throw connectionFailedError(this.baseUrl);
    }

    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new OllamaProviderError(
        'COMPLETION_FAILED',
        `Ollama request failed: ${response.status} ${detail}`,
      );
    }

    let json: OllamaChatResponse;
    try {
      json = (await response.json()) as OllamaChatResponse;
    } catch (error) {
      throw new OllamaProviderError(
        'COMPLETION_FAILED',
        `Ollama returned invalid JSON: ${String(error)}`,
      );
    }

    const content = typeof json.message?.content === 'string' ? json.message.content : '';
    return {
      content,
      provider: this.id,
      model: this.model,
      promptTokens: numberOrUndefined(json.prompt_eval_count),
      completionTokens: numberOrUndefined(json.eval_count),
    };
  }

  /** No persistent resources to release (no worker, no in-flight-request tracking needed for a stateless fetch-based provider). */
  async dispose(): Promise<void> {}
}
