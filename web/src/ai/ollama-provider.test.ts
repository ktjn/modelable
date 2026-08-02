import { afterEach, describe, expect, it, vi } from 'vitest';

import { listOllamaModels, OllamaProvider, OllamaProviderError } from './ollama-provider';
import type { LlmRequest } from './types';

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Error',
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('listOllamaModels', () => {
  it('parses installed model names, sorted', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ models: [{ name: 'qwen2.5-coder:14b' }, { name: 'llama3.2' }] }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const names = await listOllamaModels('http://localhost:11434');

    expect(names).toEqual(['llama3.2', 'qwen2.5-coder:14b']);
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:11434/api/tags', { method: 'GET' });
  });

  it('returns an empty list when no models are installed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ models: [] })));
    expect(await listOllamaModels('http://localhost:11434')).toEqual([]);
  });

  it('skips malformed entries', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          models: [{ name: 'llama3.2' }, 'not-an-object', { name: 123 }, {}],
        }),
      ),
    );
    expect(await listOllamaModels('http://localhost:11434')).toEqual(['llama3.2']);
  });

  it('throws CONNECTION_FAILED when the fetch itself rejects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(listOllamaModels('http://localhost:11434')).rejects.toMatchObject({
      code: 'CONNECTION_FAILED',
    });
  });

  it('throws MODEL_LIST_FAILED on a non-ok HTTP response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({}, false, 500)));
    await expect(listOllamaModels('http://localhost:11434')).rejects.toMatchObject({
      code: 'MODEL_LIST_FAILED',
    });
  });
});

describe('OllamaProvider', () => {
  const request: LlmRequest = {
    system: 'system prompt',
    user: 'user message',
    temperature: 0.2,
    responseFormat: 'text',
  };

  it('initialize() succeeds when the model is installed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ models: [{ name: 'llama3.2' }] })),
    );
    const provider = new OllamaProvider('llama3.2');
    await expect(provider.initialize()).resolves.toBeUndefined();
  });

  it('initialize() throws MODEL_NOT_INSTALLED when the model is missing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ models: [{ name: 'llama3.2' }] })),
    );
    const provider = new OllamaProvider('mistral');
    await expect(provider.initialize()).rejects.toMatchObject({ code: 'MODEL_NOT_INSTALLED' });
  });

  it('complete() posts a chat payload and parses the response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ message: { content: 'hello' }, prompt_eval_count: 12, eval_count: 4 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const provider = new OllamaProvider('llama3.2', 'http://localhost:11434');
    const response = await provider.complete(request);

    expect(response).toEqual({
      content: 'hello',
      provider: 'ollama',
      model: 'llama3.2',
      promptTokens: 12,
      completionTokens: 4,
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:11434/api/chat');
    const body = JSON.parse(init.body as string) as { model: string; stream: boolean };
    expect(body.model).toBe('llama3.2');
    expect(body.stream).toBe(false);
  });

  it('complete() throws COMPLETION_FAILED on a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({}, false, 500)));
    const provider = new OllamaProvider('llama3.2');
    await expect(provider.complete(request)).rejects.toBeInstanceOf(OllamaProviderError);
  });

  it('dispose() resolves without side effects', async () => {
    const provider = new OllamaProvider('llama3.2');
    await expect(provider.dispose()).resolves.toBeUndefined();
  });
});
