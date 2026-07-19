import type { editor } from 'monaco-editor';

import type { BrowserDiagnostic } from './protocol';

export interface NormalizedDiagnostics {
  markers: editor.IMarkerData[];
  documentDiagnostics: BrowserDiagnostic[];
}

const severity: Record<string, editor.IMarkerData['severity']> = {
  error: 8,
  warning: 4,
  info: 2,
  hint: 1,
};

export function normalizeDiagnostics(
  diagnostics: BrowserDiagnostic[],
  sourceUri: string,
): NormalizedDiagnostics {
  const markers: editor.IMarkerData[] = [];
  const documentDiagnostics: BrowserDiagnostic[] = [];
  for (const diagnostic of diagnostics) {
    if (
      diagnostic.uri !== sourceUri ||
      diagnostic.line === null ||
      diagnostic.column === null
    ) {
      documentDiagnostics.push(diagnostic);
      continue;
    }
    markers.push({
      code: diagnostic.code,
      severity: severity[diagnostic.severity] ?? 2,
      message: diagnostic.message,
      startLineNumber: Math.max(1, diagnostic.line),
      startColumn: Math.max(1, diagnostic.column),
      endLineNumber: Math.max(
        diagnostic.line,
        diagnostic.end_line ?? diagnostic.line,
      ),
      endColumn: Math.max(
        diagnostic.column + 1,
        diagnostic.end_column ?? diagnostic.column + 1,
      ),
    });
  }
  return { markers, documentDiagnostics };
}
