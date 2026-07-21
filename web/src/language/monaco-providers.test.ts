import type { languages } from 'monaco-editor';
import { describe, expect, test, vi } from 'vitest';

import type { BrowserLanguageServiceController } from './BrowserLanguageServiceController';
import { registerModelableProviders } from './monaco-providers';
import type { PlaygroundWorkspace } from '../workspace';

function workspaceAt(revision: number): PlaygroundWorkspace {
  return {
    schemaVersion: 1,
    id: 'local',
    revision,
    activeFile: 'a.mdl',
    files: [
      {
        path: 'a.mdl',
        content: 'domain demo {}',
        version: revision,
      },
    ],
  };
}

function providerHarness() {
  const disposables = [
    { dispose: vi.fn() },
    { dispose: vi.fn() },
    { dispose: vi.fn() },
    { dispose: vi.fn() },
    { dispose: vi.fn() },
  ];
  let completionProvider:
    | languages.CompletionItemProvider
    | undefined;
  let hoverProvider: languages.HoverProvider | undefined;
  let definitionProvider: languages.DefinitionProvider | undefined;
  let referenceProvider: languages.ReferenceProvider | undefined;
  let renameProvider: languages.RenameProvider | undefined;
  const monaco = {
    Range: class {
      constructor(
        readonly startLineNumber: number,
        readonly startColumn: number,
        readonly endLineNumber: number,
        readonly endColumn: number,
      ) {}
    },
    Uri: {
      parse: (uri: string) => ({ toString: () => uri }),
    },
    languages: {
      CompletionItemKind: {
        Keyword: 1,
        Snippet: 2,
        Module: 3,
        Class: 4,
        Property: 5,
        Reference: 6,
        Value: 7,
        Text: 8,
      },
      register: vi.fn(),
      registerCompletionItemProvider: vi.fn(
        (_language: string, provider: languages.CompletionItemProvider) => {
          completionProvider = provider;
          return disposables[0]!;
        },
      ),
      registerHoverProvider: vi.fn(
        (_language: string, provider: languages.HoverProvider) => {
          hoverProvider = provider;
          return disposables[1]!;
        },
      ),
      registerDefinitionProvider: vi.fn(
        (_language: string, provider: languages.DefinitionProvider) => {
          definitionProvider = provider;
          return disposables[2]!;
        },
      ),
      registerReferenceProvider: vi.fn(
        (_language: string, provider: languages.ReferenceProvider) => {
          referenceProvider = provider;
          return disposables[3]!;
        },
      ),
      registerRenameProvider: vi.fn(
        (_language: string, provider: languages.RenameProvider) => {
          renameProvider = provider;
          return disposables[4]!;
        },
      ),
    },
  };
  return {
    monaco,
    disposables,
    completion: () => completionProvider!,
    hover: () => hoverProvider!,
    definition: () => definitionProvider!,
    reference: () => referenceProvider!,
    rename: () => renameProvider!,
  };
}

const model = {
  uri: { toString: () => 'file:///a.mdl' },
} as never;
const completionContext = {} as languages.CompletionContext;
const position = (lineNumber: number, column: number) =>
  ({ lineNumber, column }) as never;

describe('registerModelableProviders', () => {
  test('completion forwards the captured revision and converts every DTO field', async () => {
    const harness = providerHarness();
    const captured = workspaceAt(8);
    const controller = {
      completion: vi.fn().mockResolvedValue({
        items: [
          {
            label: '@wire',
            kind: 'annotation',
            sort_text: '01-wire',
            detail: 'Wire annotation',
            documentation: 'Adds a wire name',
            replacement: {
              start: { line: 1, character: 0 },
              end: { line: 1, character: 2 },
            },
          },
          {
            label: 'fallback',
            kind: null,
            sort_text: '99-fallback',
            detail: null,
            documentation: null,
            replacement: null,
          },
        ],
      }),
    } as unknown as BrowserLanguageServiceController;
    const registration = registerModelableProviders(
      harness.monaco as never,
      controller,
      () => captured,
    );

    const result = await harness.completion().provideCompletionItems(
      model,
      position(2, 3),
      completionContext,
      { isCancellationRequested: false } as never,
    );

    expect(controller.completion).toHaveBeenCalledWith(
      captured,
      'file:///a.mdl',
      { line: 1, character: 2 },
    );
    expect(result).toMatchObject({
      suggestions: [
        {
          label: '@wire',
          kind: 2,
          sortText: '01-wire',
          detail: 'Wire annotation',
          documentation: 'Adds a wire name',
          range: {
            startLineNumber: 2,
            startColumn: 1,
            endLineNumber: 2,
            endColumn: 3,
          },
        },
        {
          label: 'fallback',
          kind: 8,
          sortText: '99-fallback',
          range: {
            startLineNumber: 2,
            startColumn: 3,
            endLineNumber: 2,
            endColumn: 3,
          },
        },
      ],
    });

    registration.dispose();
    registration.dispose();
    expect(
      harness.disposables.map((item) => item.dispose.mock.calls.length),
    ).toEqual([1, 1, 1, 1, 1]);
  });

  test.each([
    ['keyword', 1],
    ['annotation', 2],
    ['module', 3],
    ['class', 4],
    ['property', 5],
    ['reference', 6],
    ['value', 7],
  ])('maps %s completion items', async (kind, expected) => {
    const harness = providerHarness();
    const controller = {
      completion: vi.fn().mockResolvedValue({
        items: [
          {
            label: kind,
            kind,
            sort_text: kind,
            detail: null,
            documentation: null,
            replacement: null,
          },
        ],
      }),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(2),
    );

    const result = await harness.completion().provideCompletionItems(
      model,
      position(1, 1),
      completionContext,
      { isCancellationRequested: false } as never,
    );

    expect(result).toMatchObject({
      suggestions: [{ kind: expected }],
    });
  });

  test('suppresses cancelled and missing completion results', async () => {
    const harness = providerHarness();
    const controller = {
      completion: vi
        .fn()
        .mockResolvedValueOnce({ items: [] })
        .mockResolvedValueOnce(undefined),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(2),
    );

    await expect(
      harness.completion().provideCompletionItems(
        model,
        position(1, 1),
        completionContext,
        { isCancellationRequested: true } as never,
      ),
    ).resolves.toEqual({ suggestions: [] });
    await expect(
      harness.completion().provideCompletionItems(
        model,
        position(1, 1),
        completionContext,
        { isCancellationRequested: false } as never,
      ),
    ).resolves.toEqual({ suggestions: [] });
  });

  test('renders hover Markdown as untrusted text and suppresses stale results', async () => {
    const harness = providerHarness();
    const controller = {
      hover: vi
        .fn()
        .mockResolvedValueOnce({
          hover: {
            markdown: '[unsafe](command:run)<b>raw</b>',
            range: {
              start: { line: 0, character: 1 },
              end: { line: 0, character: 5 },
            },
          },
        })
        .mockResolvedValueOnce(undefined),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(4),
    );

    await expect(
      harness.hover().provideHover!(
        model,
        position(1, 2),
        { isCancellationRequested: false } as never,
      ),
    ).resolves.toMatchObject({
      contents: [
        {
          value: '[unsafe](command:run)<b>raw</b>',
          isTrusted: false,
          supportHtml: false,
        },
      ],
      range: {
        startLineNumber: 1,
        startColumn: 2,
        endLineNumber: 1,
        endColumn: 6,
      },
    });
    await expect(
      harness.hover().provideHover!(
        model,
        position(1, 2),
        { isCancellationRequested: false } as never,
      ),
    ).resolves.toBeNull();
  });

  test('suppresses hover after cancellation', async () => {
    const harness = providerHarness();
    const controller = {
      hover: vi.fn().mockResolvedValue({
        hover: { markdown: 'Customer', range: null },
      }),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(4),
    );

    await expect(
      harness.hover().provideHover!(
        model,
        position(1, 2),
        { isCancellationRequested: true } as never,
      ),
    ).resolves.toBeNull();
  });

  test('definition forwards the captured revision and converts location', async () => {
    const harness = providerHarness();
    const captured = workspaceAt(5);
    const controller = {
      definition: vi.fn().mockResolvedValue({
        location: {
          uri: 'file:///a.mdl',
          range: {
            start: { line: 2, character: 4 },
            end: { line: 2, character: 12 },
          },
        },
      }),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => captured,
    );

    const result = await harness.definition().provideDefinition!(
      model,
      position(3, 5),
      { isCancellationRequested: false } as never,
    );
    expect(controller.definition).toHaveBeenCalledWith(
      captured,
      'file:///a.mdl',
      { line: 2, character: 4 },
    );
    expect(result).toMatchObject({
      uri: { toString: expect.any(Function) },
      range: {
        startLineNumber: 3,
        startColumn: 5,
        endLineNumber: 3,
        endColumn: 13,
      },
    });
  });

  test('suppresses definition when location is null or cancelled', async () => {
    const harness = providerHarness();
    const controller = {
      definition: vi
        .fn()
        .mockResolvedValueOnce({ location: null })
        .mockResolvedValueOnce(undefined),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(2),
    );

    await expect(
      harness.definition().provideDefinition!(
        model,
        position(1, 1),
        { isCancellationRequested: false } as never,
      ),
    ).resolves.toBeNull();
    await expect(
      harness.definition().provideDefinition!(
        model,
        position(1, 1),
        { isCancellationRequested: true } as never,
      ),
    ).resolves.toBeNull();
  });

  test('references forwards includeDeclaration and converts locations', async () => {
    const harness = providerHarness();
    const captured = workspaceAt(6);
    const controller = {
      references: vi.fn().mockResolvedValue({
        locations: [
          {
            uri: 'file:///a.mdl',
            range: {
              start: { line: 0, character: 0 },
              end: { line: 0, character: 5 },
            },
          },
          {
            uri: 'file:///b.mdl',
            range: {
              start: { line: 1, character: 2 },
              end: { line: 1, character: 7 },
            },
          },
        ],
      }),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => captured,
    );

    const result = await harness.reference().provideReferences!(
      model,
      position(1, 1),
      { includeDeclaration: true },
      { isCancellationRequested: false } as never,
    );
    expect(controller.references).toHaveBeenCalledWith(
      captured,
      'file:///a.mdl',
      { line: 0, character: 0 },
      true,
    );
    expect(result).toHaveLength(2);
    expect(result![0]).toMatchObject({
      range: {
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: 1,
        endColumn: 6,
      },
    });
  });

  test('suppresses references when cancelled or undefined', async () => {
    const harness = providerHarness();
    const controller = {
      references: vi.fn().mockResolvedValue(undefined),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(2),
    );

    await expect(
      harness.reference().provideReferences!(
        model,
        position(1, 1),
        { includeDeclaration: false },
        { isCancellationRequested: false } as never,
      ),
    ).resolves.toBeNull();
  });

  test('rename resolveRenameLocation converts prepared rename', async () => {
    const harness = providerHarness();
    const captured = workspaceAt(7);
    const controller = {
      prepareRename: vi.fn().mockResolvedValue({
        prepared: {
          range: {
            start: { line: 1, character: 4 },
            end: { line: 1, character: 12 },
          },
          placeholder: 'Customer',
        },
      }),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => captured,
    );

    const result = await harness.rename().resolveRenameLocation!(
      model,
      position(2, 5),
      { isCancellationRequested: false } as never,
    );
    expect(result).toMatchObject({
      range: {
        startLineNumber: 2,
        startColumn: 5,
        endLineNumber: 2,
        endColumn: 13,
      },
      text: 'Customer',
    });
  });

  test('rename resolveRenameLocation rejects when prepared is null', async () => {
    const harness = providerHarness();
    const controller = {
      prepareRename: vi.fn().mockResolvedValue({ prepared: null }),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(2),
    );

    const result = await harness.rename().resolveRenameLocation!(
      model,
      position(1, 1),
      { isCancellationRequested: false } as never,
    );
    expect(result).toMatchObject({
      rejectReason: 'This element cannot be renamed.',
    });
  });

  test('rename provideRenameEdits converts workspace edit', async () => {
    const harness = providerHarness();
    const captured = workspaceAt(8);
    const controller = {
      rename: vi.fn().mockResolvedValue({
        edit: {
          edits: [
            {
              uri: 'file:///a.mdl',
              range: {
                start: { line: 1, character: 4 },
                end: { line: 1, character: 12 },
              },
              new_text: 'Client',
              expected_version: 1,
              expected_hash: 'abc',
            },
          ],
        },
      }),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => captured,
    );

    const result = await harness.rename().provideRenameEdits!(
      model,
      position(2, 5),
      'Client',
      { isCancellationRequested: false } as never,
    );
    expect(controller.rename).toHaveBeenCalledWith(
      captured,
      'file:///a.mdl',
      { line: 1, character: 4 },
      'Client',
    );
    expect(result).toMatchObject({
      edits: [
        {
          textEdit: {
            range: {
              startLineNumber: 2,
              startColumn: 5,
              endLineNumber: 2,
              endColumn: 13,
            },
            text: 'Client',
          },
        },
      ],
    });
  });

  test('suppresses rename edits when cancelled', async () => {
    const harness = providerHarness();
    const controller = {
      rename: vi.fn().mockResolvedValue(undefined),
    } as unknown as BrowserLanguageServiceController;
    registerModelableProviders(
      harness.monaco as never,
      controller,
      () => workspaceAt(2),
    );

    await expect(
      harness.rename().provideRenameEdits!(
        model,
        position(1, 1),
        'NewName',
        { isCancellationRequested: true } as never,
      ),
    ).resolves.toBeNull();
  });
});
