export const BROWSER_COMPILER_PROTOCOL_VERSION = 1 as const;

export type BrowserCompilerMethod =
  | 'runtime.initialize'
  | 'workspace.open'
  | 'source.format'
  | 'compile.jsonSchema';

export type BrowserCompilerErrorCode =
  | 'INITIALIZATION_FAILED'
  | 'INVALID_REQUEST'
  | 'UNSUPPORTED_PROTOCOL'
  | 'COMPILER_FAILED';

export interface BrowserCompilerRequest {
  protocolVersion: typeof BROWSER_COMPILER_PROTOCOL_VERSION;
  id: string;
  method: BrowserCompilerMethod;
  payload: unknown;
}

export interface BrowserCompilerSuccess<T = unknown> {
  protocolVersion: typeof BROWSER_COMPILER_PROTOCOL_VERSION;
  id: string;
  ok: true;
  result: T;
}

export interface BrowserCompilerFailure {
  protocolVersion: typeof BROWSER_COMPILER_PROTOCOL_VERSION;
  id: string;
  ok: false;
  error: {
    code: BrowserCompilerErrorCode;
    message: string;
  };
}

export type BrowserCompilerResponse<T = unknown> =
  | BrowserCompilerSuccess<T>
  | BrowserCompilerFailure;

export interface BrowserSource {
  uri: string;
  text: string;
  version: number;
}

export interface BrowserDiagnostic {
  code: string;
  severity: string;
  message: string;
  uri: string;
  line: number | null;
  column: number | null;
  end_line: number | null;
  end_column: number | null;
}

export interface BrowserArtifact {
  path: string;
  media_type: string;
  content: string;
  source_refs: string[];
}

export interface BrowserWorkspaceResult {
  diagnostics: BrowserDiagnostic[];
  source_hashes: Record<string, string>;
}

export interface BrowserFormatResult {
  diagnostics: BrowserDiagnostic[];
  replacement_text: string | null;
}

export interface BrowserCompileResult {
  diagnostics: BrowserDiagnostic[];
  artifacts: BrowserArtifact[];
}

const methods = new Set<BrowserCompilerMethod>([
  'runtime.initialize',
  'workspace.open',
  'source.format',
  'compile.jsonSchema',
]);

const errorCodes = new Set<BrowserCompilerErrorCode>([
  'INITIALIZATION_FAILED',
  'INVALID_REQUEST',
  'UNSUPPORTED_PROTOCOL',
  'COMPILER_FAILED',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasValidEnvelope(value: Record<string, unknown>): boolean {
  return (
    value.protocolVersion === BROWSER_COMPILER_PROTOCOL_VERSION &&
    typeof value.id === 'string' &&
    value.id.length > 0
  );
}

export function isBrowserCompilerRequest(
  value: unknown,
): value is BrowserCompilerRequest {
  return (
    isRecord(value) &&
    hasValidEnvelope(value) &&
    typeof value.method === 'string' &&
    methods.has(value.method as BrowserCompilerMethod) &&
    Object.hasOwn(value, 'payload')
  );
}

export function isBrowserCompilerResponse(
  value: unknown,
): value is BrowserCompilerResponse {
  if (!isRecord(value) || !hasValidEnvelope(value)) {
    return false;
  }
  if (value.ok === true) {
    return Object.hasOwn(value, 'result');
  }
  if (value.ok !== false || !isRecord(value.error)) {
    return false;
  }
  return (
    typeof value.error.code === 'string' &&
    errorCodes.has(value.error.code as BrowserCompilerErrorCode) &&
    typeof value.error.message === 'string'
  );
}
