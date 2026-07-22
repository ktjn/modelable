import { describe, expect, test } from 'vitest';

import {
  BROWSER_COMPILER_PROTOCOL_VERSION,
  isBrowserAiExplainResult,
  isBrowserAiGenerateResult,
  isBrowserAiPendingResult,
  isBrowserAiResult,
  isBrowserCompatibilityResult,
  isBrowserCompletionResult,
  isBrowserCompilerRequest,
  isBrowserCompilerResponse,
  isBrowserDefinitionResult,
  isBrowserGovernanceResult,
  isBrowserHoverResult,
  isBrowserLanguageLocation,
  isBrowserLineageResult,
  isBrowserPreparedRenameResult,
  isBrowserReferencesResult,
  isBrowserRenameResult,
  isBrowserWorkspaceResult,
} from './protocol';

describe('isBrowserCompilerRequest', () => {
  const valid = {
    protocolVersion: 2,
    id: 'request-1',
    method: 'workspace.open',
    payload: { sources: [] },
  };

  test.each([null, undefined, 1, 'request', []])(
    'rejects non-object value %j',
    (value) => {
      expect(isBrowserCompilerRequest(value)).toBe(false);
    },
  );

  test('rejects unsupported protocol versions', () => {
    expect(isBrowserCompilerRequest({ ...valid, protocolVersion: 1 })).toBe(
      false,
    );
  });

  test.each([undefined, '', 42])('rejects invalid request IDs %j', (id) => {
    expect(isBrowserCompilerRequest({ ...valid, id })).toBe(false);
  });

  test('rejects unknown methods', () => {
    expect(
      isBrowserCompilerRequest({ ...valid, method: 'compile.unknown' }),
    ).toBe(false);
  });

  test('accepts a valid request', () => {
    expect(isBrowserCompilerRequest(valid)).toBe(true);
  });
});

describe('isBrowserCompilerResponse', () => {
  const success = {
    protocolVersion: 2,
    id: 'request-1',
    ok: true,
    result: undefined,
  };

  test.each([null, undefined, 1, 'response', []])(
    'rejects non-object value %j',
    (value) => {
      expect(isBrowserCompilerResponse(value)).toBe(false);
    },
  );

  test('rejects unsupported protocol versions', () => {
    expect(
      isBrowserCompilerResponse({ ...success, protocolVersion: 1 }),
    ).toBe(false);
  });

  test.each([undefined, '', 42])('rejects invalid response IDs %j', (id) => {
    expect(isBrowserCompilerResponse({ ...success, id })).toBe(false);
  });

  test('rejects success envelopes without a result property', () => {
    const { result: _result, ...withoutResult } = success;
    expect(isBrowserCompilerResponse(withoutResult)).toBe(false);
  });

  test('rejects failures with unknown error codes', () => {
    expect(
      isBrowserCompilerResponse({
        protocolVersion: 2,
        id: 'request-1',
        ok: false,
        error: { code: 'SECRET_ERROR', message: 'nope' },
      }),
    ).toBe(false);
  });

  test('accepts valid success and failure responses', () => {
    expect(isBrowserCompilerResponse(success)).toBe(true);
    expect(
      isBrowserCompilerResponse({
        protocolVersion: 2,
        id: 'request-1',
        ok: false,
        error: { code: 'COMPILER_FAILED', message: 'Compiler failed' },
      }),
    ).toBe(true);
  });
});

describe('browser protocol v2 result guards', () => {
  const range = {
    start: { line: 1, character: 2 },
    end: { line: 1, character: 4 },
  };
  const diagnostic = {
    code: 'parse',
    severity: 'error',
    message: 'Invalid syntax',
    uri: 'file:///a.mdl',
    line: 1,
    column: 2,
    end_line: 1,
    end_column: 4,
  };
  const completion = {
    label: 'x',
    kind: 'property',
    sort_text: '001',
    detail: null,
    documentation: null,
    replacement: range,
  };

  test('uses protocol version 2', () => {
    expect(BROWSER_COMPILER_PROTOCOL_VERSION).toBe(2);
  });

  test('accepts exact workspace, completion, and hover results', () => {
    expect(
      isBrowserWorkspaceResult({
        workspace_revision: 4,
        diagnostics: [diagnostic],
        source_hashes: { 'file:///a.mdl': 'abc' },
      }),
    ).toBe(true);
    expect(isBrowserCompletionResult({ items: [completion] })).toBe(true);
    expect(
      isBrowserHoverResult({ hover: { markdown: '**x**', range } }),
    ).toBe(true);
    expect(isBrowserHoverResult({ hover: null })).toBe(true);
    expect(
      isBrowserWorkspaceResult({
        workspace_revision: 4,
        diagnostics: [{ ...diagnostic, line: -1, column: -1 }],
        source_hashes: { 'file:///a.mdl': 'abc' },
      }),
    ).toBe(true);
  });

  test('rejects unknown fields at every nested language level', () => {
    expect(
      isBrowserCompletionResult({
        items: [{ ...completion, extra: true }],
      }),
    ).toBe(false);
    expect(
      isBrowserCompletionResult({
        items: [
          {
            ...completion,
            replacement: {
              ...range,
              start: { ...range.start, extra: true },
            },
          },
        ],
      }),
    ).toBe(false);
    expect(
      isBrowserHoverResult({
        hover: { markdown: '**x**', range, extra: true },
      }),
    ).toBe(false);
  });

  test('validates exact language locations and their nested ranges', () => {
    expect(
      isBrowserLanguageLocation({ uri: 'file:///a.mdl', range }),
    ).toBe(true);
    expect(
      isBrowserLanguageLocation({
        uri: 'file:///a.mdl',
        range,
        extra: true,
      }),
    ).toBe(false);
    expect(isBrowserLanguageLocation({ uri: '', range })).toBe(false);
  });

  test('rejects invalid nested ranges, versions, hashes, and diagnostics', () => {
    expect(
      isBrowserCompletionResult({
        items: [
          {
            ...completion,
            replacement: {
              start: { line: 1, character: 4 },
              end: { line: 1, character: 2 },
            },
          },
        ],
      }),
    ).toBe(false);
    expect(
      isBrowserWorkspaceResult({
        workspace_revision: 0,
        diagnostics: [],
        source_hashes: {},
      }),
    ).toBe(false);
    expect(
      isBrowserWorkspaceResult({
        workspace_revision: 4,
        diagnostics: [{ ...diagnostic, extra: true }],
        source_hashes: {},
      }),
    ).toBe(false);
    expect(
      isBrowserWorkspaceResult({
        workspace_revision: 4,
        diagnostics: [],
        source_hashes: { 'file:///a.mdl': 42 },
      }),
    ).toBe(false);
  });

  test('accepts and validates definition, references, prepareRename, and rename results', () => {
    expect(isBrowserDefinitionResult({ location: null })).toBe(true);
    expect(
      isBrowserDefinitionResult({
        location: { uri: 'file:///a.mdl', range },
      }),
    ).toBe(true);
    expect(isBrowserDefinitionResult({ location: 'invalid' })).toBe(false);
    expect(
      isBrowserDefinitionResult({ location: null, extra: true }),
    ).toBe(false);

    expect(isBrowserReferencesResult({ locations: [] })).toBe(true);
    expect(
      isBrowserReferencesResult({
        locations: [{ uri: 'file:///a.mdl', range }],
      }),
    ).toBe(true);
    expect(isBrowserReferencesResult({ locations: [{}] })).toBe(false);
    expect(
      isBrowserReferencesResult({ locations: [], extra: true }),
    ).toBe(false);

    expect(isBrowserPreparedRenameResult({ prepared: null })).toBe(true);
    expect(
      isBrowserPreparedRenameResult({
        prepared: { range, placeholder: 'Customer' },
      }),
    ).toBe(true);
    expect(
      isBrowserPreparedRenameResult({
        prepared: { range, placeholder: 42 },
      }),
    ).toBe(false);
    expect(
      isBrowserPreparedRenameResult({ prepared: null, extra: true }),
    ).toBe(false);

    const edit = {
      uri: 'file:///a.mdl',
      range,
      new_text: 'Client',
      expected_version: 1,
      expected_hash: 'abc',
    };
    expect(isBrowserRenameResult({ edit: { edits: [edit] } })).toBe(true);
    expect(isBrowserRenameResult({ edit: { edits: [] } })).toBe(true);
    expect(
      isBrowserRenameResult({
        edit: { edits: [{ ...edit, expected_version: 0 }] },
      }),
    ).toBe(false);
    expect(
      isBrowserRenameResult({ edit: { edits: [{ ...edit, extra: true }] } }),
    ).toBe(false);
    expect(isBrowserRenameResult({ edit: { edits: [], extra: true } })).toBe(
      false,
    );
  });

  test('rejects unknown fields in envelopes and typed errors', () => {
    expect(
      isBrowserCompilerResponse({
        protocolVersion: 2,
        id: 'request-1',
        ok: true,
        result: null,
        extra: true,
      }),
    ).toBe(false);
    expect(
      isBrowserCompilerResponse({
        protocolVersion: 2,
        id: 'request-1',
        ok: false,
        error: {
          code: 'STALE_WORKSPACE',
          message: 'stale',
          extra: true,
        },
      }),
    ).toBe(false);
  });
});

describe('isBrowserLineageResult', () => {
  const valid = {
    workspace_revision: 100,
    projections: [
      {
        domain: 'billing',
        projection: 'BillingCustomer',
        version: 1,
        fields: [
          {
            field_name: 'id',
            kind: 'direct' as const,
            lineage: ['customer.Customer@2.customerId'],
            expression: null,
          },
        ],
      },
    ],
  };

  test('accepts valid lineage result', () => {
    expect(isBrowserLineageResult(valid)).toBe(true);
  });

  test('accepts empty projections', () => {
    expect(
      isBrowserLineageResult({ workspace_revision: 1, projections: [] }),
    ).toBe(true);
  });

  test('rejects missing workspace_revision', () => {
    expect(isBrowserLineageResult({ projections: [] })).toBe(false);
  });

  test('rejects invalid field kind', () => {
    const projection = valid.projections[0]!;
    const field = projection.fields[0]!;
    const invalid = {
      ...valid,
      projections: [
        {
          ...projection,
          fields: [{ ...field, kind: 'unknown' }],
        },
      ],
    };
    expect(isBrowserLineageResult(invalid)).toBe(false);
  });
});

describe('isBrowserCompatibilityResult', () => {
  const valid = {
    workspace_revision: 100,
    reports: [
      {
        domain_name: 'customer',
        model_name: 'Customer',
        from_version: 1,
        to_version: 2,
        status: 'compatible',
        findings: ['added_field email'],
        changes: [
          {
            kind: 'added_field',
            field_name: 'email',
            previous_name: null,
            replacement: null,
            from_optional: null,
            to_optional: true,
            from_type: null,
            to_type: '"string"',
          },
        ],
      },
    ],
    impacts: [],
  };

  test('accepts valid compatibility result', () => {
    expect(isBrowserCompatibilityResult(valid)).toBe(true);
  });

  test('accepts empty reports and impacts', () => {
    expect(
      isBrowserCompatibilityResult({
        workspace_revision: 1,
        reports: [],
        impacts: [],
      }),
    ).toBe(true);
  });

  test('rejects missing impacts', () => {
    expect(
      isBrowserCompatibilityResult({
        workspace_revision: 1,
        reports: [],
      }),
    ).toBe(false);
  });
});

describe('isBrowserGovernanceResult', () => {
  const valid = {
    workspace_revision: 100,
    findings: [
      {
        code: 'missing_project_grant',
        subject: 'billing.BillingCustomer@1',
        message: 'billing.BillingCustomer@1 has no documented project grant',
      },
    ],
  };

  test('accepts valid governance result', () => {
    expect(isBrowserGovernanceResult(valid)).toBe(true);
  });

  test('accepts empty findings', () => {
    expect(
      isBrowserGovernanceResult({ workspace_revision: 1, findings: [] }),
    ).toBe(true);
  });

  test('rejects finding with extra fields', () => {
    expect(
      isBrowserGovernanceResult({
        workspace_revision: 1,
        findings: [{ ...valid.findings[0], extra: true }],
      }),
    ).toBe(false);
  });

  test('rejects non-object', () => {
    expect(isBrowserGovernanceResult(null)).toBe(false);
  });
});

describe('isBrowserAiPendingResult', () => {
  const valid = {
    status: 'pending_llm',
    llm_request: {
      system: 'You are a helper.',
      user: 'Generate an entity.',
      temperature: 0.2,
      response_format: 'text',
    },
  };

  test('accepts valid pending result', () => {
    expect(isBrowserAiPendingResult(valid)).toBe(true);
  });

  test('rejects wrong status', () => {
    expect(isBrowserAiPendingResult({ ...valid, status: 'ready' })).toBe(false);
  });

  test('rejects missing llm_request', () => {
    expect(isBrowserAiPendingResult({ status: 'pending_llm' })).toBe(false);
  });

  test('rejects non-object', () => {
    expect(isBrowserAiPendingResult(null)).toBe(false);
  });
});

describe('isBrowserAiGenerateResult', () => {
  const valid = {
    source: 'domain example\n  entity Foo @1\n    fooId uuid @key',
    diagnostics: [],
  };

  test('accepts valid generate result', () => {
    expect(isBrowserAiGenerateResult(valid)).toBe(true);
  });

  test('accepts result with diagnostics', () => {
    expect(
      isBrowserAiGenerateResult({
        source: 'invalid',
        diagnostics: [
          {
            code: 'PARSE',
            severity: 'error',
            message: 'Unexpected token',
            uri: 'ai-generated.mdl',
            line: 1,
            column: 0,
            end_line: null,
            end_column: null,
          },
        ],
      }),
    ).toBe(true);
  });

  test('rejects missing source', () => {
    expect(isBrowserAiGenerateResult({ diagnostics: [] })).toBe(false);
  });

  test('rejects non-object', () => {
    expect(isBrowserAiGenerateResult(null)).toBe(false);
  });
});

describe('isBrowserAiExplainResult', () => {
  test('accepts valid explain result', () => {
    expect(
      isBrowserAiExplainResult({ explanation: 'This model represents...' }),
    ).toBe(true);
  });

  test('rejects missing explanation', () => {
    expect(isBrowserAiExplainResult({})).toBe(false);
  });

  test('rejects non-string explanation', () => {
    expect(isBrowserAiExplainResult({ explanation: 42 })).toBe(false);
  });

  test('rejects non-object', () => {
    expect(isBrowserAiExplainResult(null)).toBe(false);
  });
});

describe('isBrowserAiResult', () => {
  test('accepts pending result', () => {
    expect(
      isBrowserAiResult({
        status: 'pending_llm',
        llm_request: {
          system: 's',
          user: 'u',
          temperature: 0.2,
          response_format: 'text',
        },
      }),
    ).toBe(true);
  });

  test('accepts generate result', () => {
    expect(
      isBrowserAiResult({ source: 'domain d\n  entity E @1', diagnostics: [] }),
    ).toBe(true);
  });

  test('accepts explain result', () => {
    expect(isBrowserAiResult({ explanation: 'text' })).toBe(true);
  });

  test('rejects unknown shape', () => {
    expect(isBrowserAiResult({ unknown: true })).toBe(false);
  });
});

describe('isBrowserCompilerRequest with AI methods', () => {
  test('accepts ai.generate method', () => {
    expect(
      isBrowserCompilerRequest({
        protocolVersion: BROWSER_COMPILER_PROTOCOL_VERSION,
        id: 'req-1',
        method: 'ai.generate',
        payload: {},
      }),
    ).toBe(true);
  });

  test('accepts ai.explain method', () => {
    expect(
      isBrowserCompilerRequest({
        protocolVersion: BROWSER_COMPILER_PROTOCOL_VERSION,
        id: 'req-2',
        method: 'ai.explain',
        payload: {},
      }),
    ).toBe(true);
  });
});
