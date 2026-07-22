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

export type AiGenerateAction =
  | 'generate_entity'
  | 'suggest_projection';

export type AiExplainAction = 'explain';

export interface AiGenerateParameters {
  description?: string;
  domainName?: string;
  modelName?: string;
  sourceRef?: string;
  consumerDomain?: string;
}

export interface AiExplainParameters {
  ref?: string;
  diagnosticIndex?: number;
}

export interface AiGenerateResult {
  source: string;
  diagnostics: import('../protocol').BrowserDiagnostic[];
}

export interface AiExplainResult {
  explanation: string;
}

export type ProviderStatus =
  | 'idle'
  | 'detecting'
  | 'downloading'
  | 'ready'
  | 'error'
  | 'unsupported';
