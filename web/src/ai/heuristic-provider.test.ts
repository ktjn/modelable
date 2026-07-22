import { describe, expect, test } from 'vitest';

import { HeuristicProvider } from './heuristic-provider';
import type { LlmRequest } from './types';

describe('HeuristicProvider', () => {
  test('has heuristic id and model', () => {
    const provider = new HeuristicProvider();
    expect(provider.id).toBe('heuristic');
    expect(provider.model).toBe('heuristic');
  });

  test('initialize resolves without error', async () => {
    const provider = new HeuristicProvider();
    await expect(provider.initialize()).resolves.toBeUndefined();
  });

  test('complete returns user text for text format', async () => {
    const provider = new HeuristicProvider();
    const request: LlmRequest = {
      system: 'You are a helper.',
      user: 'domain example\n  entity Foo @1',
      temperature: 0.2,
      responseFormat: 'text',
    };
    const response = await provider.complete(request);
    expect(response.content).toBe(request.user);
    expect(response.provider).toBe('heuristic');
    expect(response.model).toBe('heuristic');
  });

  test('complete returns JSON-wrapped user text for json format', async () => {
    const provider = new HeuristicProvider();
    const request: LlmRequest = {
      system: 'You are a helper.',
      user: 'explain this model',
      temperature: 0.2,
      responseFormat: 'json',
    };
    const response = await provider.complete(request);
    expect(JSON.parse(response.content)).toEqual({ result: request.user });
  });

  test('dispose resolves without error', async () => {
    const provider = new HeuristicProvider();
    await expect(provider.dispose()).resolves.toBeUndefined();
  });
});
