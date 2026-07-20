import { describe, expect, test } from 'vitest';

import {
  normalizeDiagnostics,
  normalizeDiagnosticsByUri,
} from './diagnostics';
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

test('routes markers to every matching file model', () => {
  const result = normalizeDiagnosticsByUri(
    [
      { ...ranged, uri: 'file:///a.mdl' },
      { ...ranged, uri: 'file:///b.mdl' },
      { ...ranged, uri: 'file:///b.mdl', code: 'E200' },
      { ...ranged, uri: 'file:///outside.mdl' },
    ],
    ['file:///a.mdl', 'file:///b.mdl'],
  );

  expect(result.get('file:///a.mdl')).toHaveLength(1);
  expect(result.get('file:///b.mdl')).toHaveLength(2);
});
