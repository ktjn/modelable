export const BROWSER_COMPILER_PROTOCOL_VERSION = 2 as const;

export type BrowserCompilerMethod =
  | 'runtime.initialize'
  | 'workspace.open'
  | 'source.format'
  | 'compile.jsonSchema'
  | 'language.completion'
  | 'language.hover'
  | 'language.definition'
  | 'language.references'
  | 'language.prepareRename'
  | 'language.rename';

export type BrowserCompilerErrorCode =
  | 'INITIALIZATION_FAILED'
  | 'INVALID_REQUEST'
  | 'UNSUPPORTED_PROTOCOL'
  | 'COMPILER_FAILED'
  | 'STALE_WORKSPACE'
  | 'LANGUAGE_UNAVAILABLE'
  | 'INVALID_POSITION'
  | 'INVALID_RENAME'
  | 'STALE_EDIT';

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
  workspace_revision: number;
  diagnostics: BrowserDiagnostic[];
  source_hashes: Record<string, string>;
}

export interface BrowserLanguagePosition {
  workspaceRevision: number;
  uri: string;
  line: number;
  character: number;
}

export interface BrowserLanguagePositionValue {
  line: number;
  character: number;
}

export interface BrowserLanguageRange {
  start: BrowserLanguagePositionValue;
  end: BrowserLanguagePositionValue;
}

export interface BrowserLanguageLocation {
  uri: string;
  range: BrowserLanguageRange;
}

export type BrowserCompletionKind =
  | 'keyword'
  | 'annotation'
  | 'module'
  | 'class'
  | 'property'
  | 'reference'
  | 'value';

export interface BrowserCompletion {
  label: string;
  kind: BrowserCompletionKind | null;
  sort_text: string;
  detail: string | null;
  documentation: string | null;
  replacement: BrowserLanguageRange | null;
}

export interface BrowserCompletionResult {
  items: BrowserCompletion[];
}

export interface BrowserHover {
  markdown: string;
  range: BrowserLanguageRange | null;
}

export interface BrowserHoverResult {
  hover: BrowserHover | null;
}

export interface BrowserFormatResult {
  diagnostics: BrowserDiagnostic[];
  replacement_text: string | null;
}

export interface BrowserDefinitionResult {
  location: BrowserLanguageLocation | null;
}

export interface BrowserReferencesResult {
  locations: BrowserLanguageLocation[];
}

export interface BrowserPreparedRenameResult {
  prepared: BrowserPreparedRename | null;
}

export interface BrowserPreparedRename {
  range: BrowserLanguageRange;
  placeholder: string;
}

export interface BrowserTextEdit {
  uri: string;
  range: BrowserLanguageRange;
  new_text: string;
  expected_version: number;
  expected_hash: string;
}

export interface BrowserWorkspaceEdit {
  edits: BrowserTextEdit[];
}

export interface BrowserRenameResult {
  edit: BrowserWorkspaceEdit;
}

export interface BrowserCompileResult {
  diagnostics: BrowserDiagnostic[];
  artifacts: BrowserArtifact[];
}

export type BrowserResultGuard<T> = (value: unknown) => value is T;

const methods = new Set<BrowserCompilerMethod>([
  'runtime.initialize',
  'workspace.open',
  'source.format',
  'compile.jsonSchema',
  'language.completion',
  'language.hover',
  'language.definition',
  'language.references',
  'language.prepareRename',
  'language.rename',
]);

const errorCodes = new Set<BrowserCompilerErrorCode>([
  'INITIALIZATION_FAILED',
  'INVALID_REQUEST',
  'UNSUPPORTED_PROTOCOL',
  'COMPILER_FAILED',
  'STALE_WORKSPACE',
  'LANGUAGE_UNAVAILABLE',
  'INVALID_POSITION',
  'INVALID_RENAME',
  'STALE_EDIT',
]);

const completionKinds = new Set<BrowserCompletionKind>([
  'keyword',
  'annotation',
  'module',
  'class',
  'property',
  'reference',
  'value',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value);
  return (
    actual.length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key))
  );
}

function isIntegerAtLeast(value: unknown, minimum: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= minimum;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableCoordinate(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === 'number' &&
      Number.isInteger(value) &&
      value >= -1)
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return isRecord(value) && Object.values(value).every((item) => typeof item === 'string');
}

function hasValidEnvelope(value: Record<string, unknown>): boolean {
  return (
    value.protocolVersion === BROWSER_COMPILER_PROTOCOL_VERSION &&
    typeof value.id === 'string' &&
    value.id.length > 0
  );
}

function comparePositions(
  left: BrowserLanguagePositionValue,
  right: BrowserLanguagePositionValue,
): number {
  return left.line - right.line || left.character - right.character;
}

export function isBrowserLanguagePositionValue(
  value: unknown,
): value is BrowserLanguagePositionValue {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['line', 'character']) &&
    isIntegerAtLeast(value.line, 0) &&
    isIntegerAtLeast(value.character, 0)
  );
}

export function isBrowserLanguageRange(
  value: unknown,
): value is BrowserLanguageRange {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['start', 'end']) &&
    isBrowserLanguagePositionValue(value.start) &&
    isBrowserLanguagePositionValue(value.end) &&
    comparePositions(value.start, value.end) <= 0
  );
}

export function isBrowserLanguageLocation(
  value: unknown,
): value is BrowserLanguageLocation {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['uri', 'range']) &&
    typeof value.uri === 'string' &&
    value.uri.length > 0 &&
    isBrowserLanguageRange(value.range)
  );
}

export function isBrowserDiagnostic(
  value: unknown,
): value is BrowserDiagnostic {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'code',
      'severity',
      'message',
      'uri',
      'line',
      'column',
      'end_line',
      'end_column',
    ]) &&
    typeof value.code === 'string' &&
    typeof value.severity === 'string' &&
    typeof value.message === 'string' &&
    typeof value.uri === 'string' &&
    isNullableCoordinate(value.line) &&
    isNullableCoordinate(value.column) &&
    isNullableCoordinate(value.end_line) &&
    isNullableCoordinate(value.end_column)
  );
}

export function isBrowserArtifact(value: unknown): value is BrowserArtifact {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['path', 'media_type', 'content', 'source_refs']) &&
    typeof value.path === 'string' &&
    typeof value.media_type === 'string' &&
    typeof value.content === 'string' &&
    isStringArray(value.source_refs)
  );
}

export function isBrowserWorkspaceResult(
  value: unknown,
): value is BrowserWorkspaceResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'workspace_revision',
      'diagnostics',
      'source_hashes',
    ]) &&
    isIntegerAtLeast(value.workspace_revision, 1) &&
    Array.isArray(value.diagnostics) &&
    value.diagnostics.every(isBrowserDiagnostic) &&
    isStringRecord(value.source_hashes)
  );
}

export function isBrowserCompletionResult(
  value: unknown,
): value is BrowserCompletionResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['items']) &&
    Array.isArray(value.items) &&
    value.items.every(
      (item): item is BrowserCompletion =>
        isRecord(item) &&
        hasExactKeys(item, [
          'label',
          'kind',
          'sort_text',
          'detail',
          'documentation',
          'replacement',
        ]) &&
        typeof item.label === 'string' &&
        (item.kind === null ||
          (typeof item.kind === 'string' &&
            completionKinds.has(item.kind as BrowserCompletionKind))) &&
        typeof item.sort_text === 'string' &&
        isNullableString(item.detail) &&
        isNullableString(item.documentation) &&
        (item.replacement === null ||
          isBrowserLanguageRange(item.replacement)),
    )
  );
}

export function isBrowserHoverResult(
  value: unknown,
): value is BrowserHoverResult {
  if (!isRecord(value) || !hasExactKeys(value, ['hover'])) {
    return false;
  }
  return (
    value.hover === null ||
    (isRecord(value.hover) &&
      hasExactKeys(value.hover, ['markdown', 'range']) &&
      typeof value.hover.markdown === 'string' &&
      (value.hover.range === null ||
        isBrowserLanguageRange(value.hover.range)))
  );
}

export function isBrowserDefinitionResult(
  value: unknown,
): value is BrowserDefinitionResult {
  if (!isRecord(value) || !hasExactKeys(value, ['location'])) {
    return false;
  }
  return value.location === null || isBrowserLanguageLocation(value.location);
}

export function isBrowserReferencesResult(
  value: unknown,
): value is BrowserReferencesResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['locations']) &&
    Array.isArray(value.locations) &&
    value.locations.every(isBrowserLanguageLocation)
  );
}

function isBrowserPreparedRename(
  value: unknown,
): value is BrowserPreparedRename {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['range', 'placeholder']) &&
    isBrowserLanguageRange(value.range) &&
    typeof value.placeholder === 'string'
  );
}

export function isBrowserPreparedRenameResult(
  value: unknown,
): value is BrowserPreparedRenameResult {
  if (!isRecord(value) || !hasExactKeys(value, ['prepared'])) {
    return false;
  }
  return value.prepared === null || isBrowserPreparedRename(value.prepared);
}

function isBrowserTextEdit(value: unknown): value is BrowserTextEdit {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'uri',
      'range',
      'new_text',
      'expected_version',
      'expected_hash',
    ]) &&
    typeof value.uri === 'string' &&
    isBrowserLanguageRange(value.range) &&
    typeof value.new_text === 'string' &&
    isIntegerAtLeast(value.expected_version, 1) &&
    typeof value.expected_hash === 'string'
  );
}

export function isBrowserRenameResult(
  value: unknown,
): value is BrowserRenameResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['edit']) &&
    isRecord(value.edit) &&
    hasExactKeys(value.edit, ['edits']) &&
    Array.isArray(value.edit.edits) &&
    value.edit.edits.every(isBrowserTextEdit)
  );
}

export function isBrowserFormatResult(
  value: unknown,
): value is BrowserFormatResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['diagnostics', 'replacement_text']) &&
    Array.isArray(value.diagnostics) &&
    value.diagnostics.every(isBrowserDiagnostic) &&
    isNullableString(value.replacement_text)
  );
}

export function isBrowserCompileResult(
  value: unknown,
): value is BrowserCompileResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['diagnostics', 'artifacts']) &&
    Array.isArray(value.diagnostics) &&
    value.diagnostics.every(isBrowserDiagnostic) &&
    Array.isArray(value.artifacts) &&
    value.artifacts.every(isBrowserArtifact)
  );
}

export function isBrowserCompilerRequest(
  value: unknown,
): value is BrowserCompilerRequest {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['protocolVersion', 'id', 'method', 'payload']) &&
    hasValidEnvelope(value) &&
    typeof value.method === 'string' &&
    methods.has(value.method as BrowserCompilerMethod)
  );
}

export function isBrowserCompilerResponse(
  value: unknown,
): value is BrowserCompilerResponse {
  if (!isRecord(value) || !hasValidEnvelope(value)) {
    return false;
  }
  if (value.ok === true) {
    return (
      hasExactKeys(value, ['protocolVersion', 'id', 'ok', 'result'])
    );
  }
  if (
    value.ok !== false ||
    !hasExactKeys(value, ['protocolVersion', 'id', 'ok', 'error']) ||
    !isRecord(value.error)
  ) {
    return false;
  }
  return (
    hasExactKeys(value.error, ['code', 'message']) &&
    typeof value.error.code === 'string' &&
    errorCodes.has(value.error.code as BrowserCompilerErrorCode) &&
    typeof value.error.message === 'string'
  );
}
