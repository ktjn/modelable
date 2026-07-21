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
  ];
  let completionProvider:
    | languages.CompletionItemProvider
    | undefined;
  let hoverProvider: languages.HoverProvider | undefined;
  const monaco = {
    Range: class {
      constructor(
        readonly startLineNumber: number,
        readonly startColumn: number,
        readonly endLineNumber: number,
        readonly endColumn: number,
      ) {}
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
    },
  };
  return {
    monaco,
    disposables,
    completion: () => completionProvider!,
    hover: () => hoverProvider!,
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
    ).toEqual([1, 1]);
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
});
