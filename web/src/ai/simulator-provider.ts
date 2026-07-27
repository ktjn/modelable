import type { LlmProvider, LlmRequest, LlmResponse } from './types';

export interface SimulatorProviderOptions {
  malformedFirst?: boolean;
  failure?: string;
}

export class SimulatorProvider implements LlmProvider {
  readonly id = 'simulator';
  readonly model = 'semantic-v1';
  private calls = 0;

  constructor(private readonly options: SimulatorProviderOptions = {}) {}

  async initialize(): Promise<void> {}

  async complete(request: LlmRequest): Promise<LlmResponse> {
    this.calls += 1;
    if (this.options.failure !== undefined) {
      throw new Error(this.options.failure);
    }
    if (request.responseFormat === 'text') {
      return {
        content: answerFor(request.user),
        provider: this.id,
        model: this.model,
      };
    }
    const isRepair = request.user.includes(
      'Previous response validation error',
    );
    const content = this.options.malformedFirst === true
      && this.calls === 1
      && !isRepair
      ? '{malformed'
      : JSON.stringify(planFor(userRequest(request.user)));
    return {
      content,
      provider: this.id,
      model: this.model,
    };
  }

  async dispose(): Promise<void> {}
}

function userRequest(prompt: string): string {
  const match = /User request:\n([\s\S]*?)(?:\n\nPrevious response validation error:|$)/u
    .exec(prompt);
  return (match?.[1] ?? prompt).trim();
}

function answerFor(userPrompt: string): string {
  const match = /Workspace facts:\n([\s\S]*?)\n\nUser question:\n([\s\S]*?)$/u
    .exec(userPrompt);
  if (match === null) {
    return 'Here is what I found in the workspace.';
  }
  const facts = (match[1] ?? '').trim();
  const question = (match[2] ?? '').trim();
  return `Based on the workspace facts, here is the answer to '${question}':\n\n${facts}`;
}

function planFor(message: string): Record<string, unknown> {
  const normalized = message.toLowerCase();
  if (normalized.includes('describe the workspace')) {
    return {
      kind: 'query',
      query_kind: 'summary',
      refs: [],
      question: message,
    };
  }
  if (normalized.includes('create an invoice')) {
    return {
      kind: 'change_set',
      summary: 'Create billing.Invoice@1',
      operations: [{
        kind: 'create_model',
        domain: 'billing',
        name: 'Invoice',
        model_kind: 'entity',
        fields: [{
          name: 'invoiceId',
          type: { kind: 'uuid' },
          annotations: [{ kind: 'key' }],
        }],
      }],
    };
  }
  if (normalized.includes('suggest a projection')) {
    return {
      kind: 'change_set',
      summary: 'Create billing.CustomerProjection@1',
      operations: [{
        kind: 'create_projection',
        domain: 'billing',
        name: 'CustomerProjection',
        source: {
          model: 'customer.Customer',
          version: 1,
          alias: 'customer',
        },
        fields: [{
          name: 'customerId',
          mapping: {
            kind: 'direct',
            source_alias: 'customer',
            source_field: 'customerId',
          },
        }],
      }],
    };
  }
  if (normalized.includes('create a projection')) {
    return {
      kind: 'clarification',
      question: 'Which source model and consumer domain should I use?',
      reason: 'A projection requires a grounded source and consumer.',
    };
  }
  if (normalized.includes('add email')) {
    return {
      kind: 'change_set',
      summary: 'Add email to customer.Customer@2',
      operations: [
        {
          kind: 'append_model_version',
          source: 'customer.Customer@1',
          version: 2,
        },
        {
          kind: 'add_field',
          target: 'customer.Customer@2',
          field: { name: 'email', type: { kind: 'string' } },
        },
      ],
    };
  }
  if (normalized.includes('/compile json-schema')) {
    return {
      kind: 'compile',
      target: 'json-schema',
      domains: [],
      output: null,
      descriptor_set: false,
      summary: 'Compile the workspace to JSON Schema.',
    };
  }
  return {
    kind: 'unsupported',
    request: message,
    reason: 'The semantic simulator has no fixture for this request.',
  };
}
