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
  | 'language.rename'
  | 'workspace.graph'
  | 'workspace.lineage'
  | 'workspace.compatibility'
  | 'workspace.governance';

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

export type BrowserGraphMode = 'domain' | 'entity';

export interface BrowserSourceRange {
  uri: string;
  start_line: number;
  start_character: number;
  end_line: number;
  end_character: number;
}

export interface BrowserGraphNode {
  id: string;
  kind: string;
  label: string;
  metadata: Record<string, unknown>;
  source_range: BrowserSourceRange | null;
}

export interface BrowserGraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  label: string | null;
  metadata: Record<string, unknown>;
}

export interface BrowserGraph {
  schema_version: number;
  nodes: BrowserGraphNode[];
  edges: BrowserGraphEdge[];
}

export interface BrowserGraphResult {
  workspace_revision: number;
  mode: BrowserGraphMode;
  graph: BrowserGraph;
}

export interface BrowserFieldLineage {
  field_name: string;
  kind: 'direct' | 'computed';
  lineage: string[];
  expression: string | null;
}

export interface BrowserProjectionLineage {
  domain: string;
  projection: string;
  version: number;
  fields: BrowserFieldLineage[];
}

export interface BrowserLineageResult {
  workspace_revision: number;
  projections: BrowserProjectionLineage[];
}

export interface BrowserFieldChange {
  kind: string;
  field_name: string;
  previous_name: string | null;
  replacement: string | null;
  from_optional: boolean | null;
  to_optional: boolean | null;
  from_type: string | null;
  to_type: string | null;
}

export interface BrowserCompatibilityReport {
  domain_name: string;
  model_name: string;
  from_version: number;
  to_version: number;
  status: string;
  findings: string[];
  changes: BrowserFieldChange[];
}

export interface BrowserProjectionImpact {
  domain_name: string;
  projection_name: string;
  version: number;
  status: string;
  reason: string | null;
}

export interface BrowserCompatibilityResult {
  workspace_revision: number;
  reports: BrowserCompatibilityReport[];
  impacts: BrowserProjectionImpact[];
}

export interface BrowserGovernanceFinding {
  code: string;
  subject: string;
  message: string;
}

export interface BrowserGovernanceResult {
  workspace_revision: number;
  findings: BrowserGovernanceFinding[];
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
  'workspace.graph',
  'workspace.lineage',
  'workspace.compatibility',
  'workspace.governance',
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

const graphModes = new Set<BrowserGraphMode>(['domain', 'entity']);

function isBrowserSourceRange(
  value: unknown,
): value is BrowserSourceRange {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'uri',
      'start_line',
      'start_character',
      'end_line',
      'end_character',
    ]) &&
    typeof value.uri === 'string' &&
    isIntegerAtLeast(value.start_line, 0) &&
    isIntegerAtLeast(value.start_character, 0) &&
    isIntegerAtLeast(value.end_line, 0) &&
    isIntegerAtLeast(value.end_character, 0)
  );
}

function isBrowserGraphNode(value: unknown): value is BrowserGraphNode {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['id', 'kind', 'label', 'metadata', 'source_range']) &&
    typeof value.id === 'string' &&
    typeof value.kind === 'string' &&
    typeof value.label === 'string' &&
    isRecord(value.metadata) &&
    (value.source_range === null || isBrowserSourceRange(value.source_range))
  );
}

function isBrowserGraphEdge(value: unknown): value is BrowserGraphEdge {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['id', 'source', 'target', 'kind', 'label', 'metadata']) &&
    typeof value.id === 'string' &&
    typeof value.source === 'string' &&
    typeof value.target === 'string' &&
    typeof value.kind === 'string' &&
    isNullableString(value.label) &&
    isRecord(value.metadata)
  );
}

export function isBrowserGraphResult(
  value: unknown,
): value is BrowserGraphResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['workspace_revision', 'mode', 'graph']) &&
    isIntegerAtLeast(value.workspace_revision, 1) &&
    typeof value.mode === 'string' &&
    graphModes.has(value.mode as BrowserGraphMode) &&
    isRecord(value.graph) &&
    hasExactKeys(value.graph, ['schema_version', 'nodes', 'edges']) &&
    isIntegerAtLeast(value.graph.schema_version, 1) &&
    Array.isArray(value.graph.nodes) &&
    value.graph.nodes.every(isBrowserGraphNode) &&
    Array.isArray(value.graph.edges) &&
    value.graph.edges.every(isBrowserGraphEdge)
  );
}

function isBrowserFieldLineage(value: unknown): value is BrowserFieldLineage {
  return (
    isRecord(value) &&
    typeof value.field_name === 'string' &&
    (value.kind === 'direct' || value.kind === 'computed') &&
    isStringArray(value.lineage) &&
    isNullableString(value.expression)
  );
}

function isBrowserProjectionLineage(
  value: unknown,
): value is BrowserProjectionLineage {
  return (
    isRecord(value) &&
    typeof value.domain === 'string' &&
    typeof value.projection === 'string' &&
    isIntegerAtLeast(value.version, 1) &&
    Array.isArray(value.fields) &&
    value.fields.every(isBrowserFieldLineage)
  );
}

export function isBrowserLineageResult(
  value: unknown,
): value is BrowserLineageResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['workspace_revision', 'projections']) &&
    isIntegerAtLeast(value.workspace_revision, 1) &&
    Array.isArray(value.projections) &&
    value.projections.every(isBrowserProjectionLineage)
  );
}

function isNullableBoolean(value: unknown): value is boolean | null {
  return value === null || typeof value === 'boolean';
}

function isBrowserFieldChange(value: unknown): value is BrowserFieldChange {
  return (
    isRecord(value) &&
    typeof value.kind === 'string' &&
    typeof value.field_name === 'string' &&
    isNullableString(value.previous_name) &&
    isNullableString(value.replacement) &&
    isNullableBoolean(value.from_optional) &&
    isNullableBoolean(value.to_optional) &&
    isNullableString(value.from_type) &&
    isNullableString(value.to_type)
  );
}

function isBrowserCompatibilityReport(
  value: unknown,
): value is BrowserCompatibilityReport {
  return (
    isRecord(value) &&
    typeof value.domain_name === 'string' &&
    typeof value.model_name === 'string' &&
    isIntegerAtLeast(value.from_version, 1) &&
    isIntegerAtLeast(value.to_version, 1) &&
    typeof value.status === 'string' &&
    isStringArray(value.findings) &&
    Array.isArray(value.changes) &&
    value.changes.every(isBrowserFieldChange)
  );
}

function isBrowserProjectionImpact(
  value: unknown,
): value is BrowserProjectionImpact {
  return (
    isRecord(value) &&
    typeof value.domain_name === 'string' &&
    typeof value.projection_name === 'string' &&
    isIntegerAtLeast(value.version, 1) &&
    typeof value.status === 'string' &&
    isNullableString(value.reason)
  );
}

export function isBrowserCompatibilityResult(
  value: unknown,
): value is BrowserCompatibilityResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['workspace_revision', 'reports', 'impacts']) &&
    isIntegerAtLeast(value.workspace_revision, 1) &&
    Array.isArray(value.reports) &&
    value.reports.every(isBrowserCompatibilityReport) &&
    Array.isArray(value.impacts) &&
    value.impacts.every(isBrowserProjectionImpact)
  );
}

function isBrowserGovernanceFinding(
  value: unknown,
): value is BrowserGovernanceFinding {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['code', 'subject', 'message']) &&
    typeof value.code === 'string' &&
    typeof value.subject === 'string' &&
    typeof value.message === 'string'
  );
}

export function isBrowserGovernanceResult(
  value: unknown,
): value is BrowserGovernanceResult {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['workspace_revision', 'findings']) &&
    isIntegerAtLeast(value.workspace_revision, 1) &&
    Array.isArray(value.findings) &&
    value.findings.every(isBrowserGovernanceFinding)
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
