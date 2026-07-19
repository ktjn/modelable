import { describe, expect, test } from 'vitest';

import { normalizeDiagnostics } from './diagnostics';
import type { BrowserDiagnostic } from './protocol';

const ranged: BrowserDiagnostic = {
  code: 'E100',
  severity: 'error',
  message: 'Invalid field',
  uri: 'file:///main.mdl',
  line: 3,
  column: 5,
  end_line: 3,
  end_column: 9,
};

describe('normalizeDiagnostics', () => {
  test('maps current-source locations to Monaco markers', () => {
    const result = normalizeDiagnostics([ranged], 'file:///main.mdl');
    expect(result.markers).toEqual([
      expect.objectContaining({
        code: 'E100',
        message: 'Invalid field',
        startLineNumber: 3,
        startColumn: 5,
        endLineNumber: 3,
        endColumn: 9,
      }),
    ]);
    expect(result.documentDiagnostics).toEqual([]);
  });

  test('retains missing or foreign locations as document diagnostics', () => {
    const result = normalizeDiagnostics(
      [
        { ...ranged, line: null, column: null },
        { ...ranged, uri: 'file:///other.mdl' },
      ],
      'file:///main.mdl',
    );
    expect(result.markers).toEqual([]);
    expect(result.documentDiagnostics).toHaveLength(2);
  });
});
