import type { LlmProvider, LlmRequest, LlmResponse } from './types';

export class HeuristicProvider implements LlmProvider {
  readonly id = 'heuristic';
  readonly model = 'heuristic';

  async initialize(): Promise<void> {}

  async complete(request: LlmRequest): Promise<LlmResponse> {
    return {
      content: request.responseFormat === 'json'
        ? JSON.stringify({ result: request.user })
        : request.user,
      provider: this.id,
      model: this.model,
    };
  }

  async dispose(): Promise<void> {}
}
