import { describe, expect, test } from 'vitest';

import { SimulatorProvider } from './simulator-provider';
import type { LlmRequest } from './types';

function conversationRequest(message: string, repair = false): LlmRequest {
  return {
    system: 'Return JSON matching the supplied conversation plan schema.',
    user: [
      'Workspace summary:',
      'domain customer',
      '',
      `User request:\n${message}`,
      repair ? '\nPrevious response validation error:\ninvalid JSON' : '',
    ].join('\n'),
    temperature: repair ? 0.05 : 0.1,
    responseFormat: 'json',
    schema: { type: 'object' },
  };
}

describe('SimulatorProvider', () => {
  test('returns a typed create-model plan for an invoice request', async () => {
    const provider = new SimulatorProvider();

    const response = await provider.complete(
      conversationRequest('Create an invoice with an invoice id'),
    );

    expect(JSON.parse(response.content)).toMatchObject({
      kind: 'change_set',
      operations: [{ kind: 'create_model', name: 'Invoice' }],
    });
    expect(response.provider).toBe('simulator');
  });

  test('returns malformed output once then a valid repair', async () => {
    const provider = new SimulatorProvider({ malformedFirst: true });

    expect(
      (await provider.complete(conversationRequest('Create an invoice'))).content,
    ).toBe('{malformed');
    expect(
      JSON.parse(
        (
          await provider.complete(
            conversationRequest('Create an invoice', true),
          )
        ).content,
      ).kind,
    ).toBe('change_set');
  });

  test('returns projection and clarification plans by semantic intent', async () => {
    const provider = new SimulatorProvider();

    const projection = JSON.parse(
      (
        await provider.complete(
          conversationRequest('Suggest a projection for billing'),
        )
      ).content,
    );
    const clarification = JSON.parse(
      (
        await provider.complete(conversationRequest('Create a projection'))
      ).content,
    );

    expect(projection.operations[0].kind).toBe('create_projection');
    expect(clarification.kind).toBe('clarification');
  });
});
