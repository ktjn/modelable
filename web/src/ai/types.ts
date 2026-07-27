export interface LlmRequest {
  system: string;
  user: string;
  temperature: number;
  responseFormat: 'text' | 'json';
  schema?: Record<string, unknown>;
}

export interface LlmResponse {
  content: string;
  provider: string;
  model: string;
  promptTokens?: number;
  completionTokens?: number;
}

export interface LlmProvider {
  readonly id: string;
  readonly model: string;
  initialize(
    onProgress?: (progress: number, message: string) => void,
  ): Promise<void>;
  complete(request: LlmRequest): Promise<LlmResponse>;
  dispose(): Promise<void>;
}

export type ProviderStatus =
  | 'idle'
  | 'detecting'
  | 'downloading'
  | 'ready'
  | 'error'
  | 'unsupported';
