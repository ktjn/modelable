import type * as Monaco from 'monaco-editor/esm/vs/editor/editor.api.js';

import type {
  BrowserCompletion,
  BrowserCompletionKind,
  BrowserLanguagePositionValue,
  BrowserLanguageRange,
} from '../protocol';
import type { PlaygroundWorkspace } from '../workspace';
import type { BrowserLanguageServiceController } from './BrowserLanguageServiceController';

type MonacoApi = typeof Monaco;

export function registerModelableProviders(
  monaco: MonacoApi,
  controller: BrowserLanguageServiceController,
  getWorkspace: () => PlaygroundWorkspace,
): { dispose(): void } {
  monaco.languages.register({ id: 'modelable' });
  const completion = monaco.languages.registerCompletionItemProvider(
    'modelable',
    {
      async provideCompletionItems(model, position, _context, token) {
        const captured = getWorkspace();
        const result = await controller.completion(
          captured,
          model.uri.toString(),
          fromMonacoPosition(position),
        );
        if (token.isCancellationRequested || result === undefined) {
          return { suggestions: [] };
        }
        return {
          suggestions: result.items.map((item) =>
            toMonacoCompletion(monaco, item, position),
          ),
        };
      },
    },
  );
  const hover = monaco.languages.registerHoverProvider('modelable', {
    async provideHover(model, position, token) {
      const captured = getWorkspace();
      const result = await controller.hover(
        captured,
        model.uri.toString(),
        fromMonacoPosition(position),
      );
      if (
        token.isCancellationRequested ||
        result === undefined ||
        result.hover === null
      ) {
        return null;
      }
      return {
        contents: [
          {
            value: result.hover.markdown,
            isTrusted: false,
            supportHtml: false,
          },
        ],
        range:
          result.hover.range === null
            ? undefined
            : toMonacoRange(monaco, result.hover.range),
      };
    },
  });
  let disposed = false;
  return {
    dispose() {
      if (disposed) {
        return;
      }
      disposed = true;
      completion.dispose();
      hover.dispose();
    },
  };
}

function fromMonacoPosition(
  position: Monaco.Position,
): BrowserLanguagePositionValue {
  return {
    line: position.lineNumber - 1,
    character: position.column - 1,
  };
}

function toMonacoCompletion(
  monaco: MonacoApi,
  item: BrowserCompletion,
  position: Monaco.Position,
): Monaco.languages.CompletionItem {
  return {
    label: item.label,
    kind: toMonacoCompletionKind(monaco, item.kind),
    sortText: item.sort_text,
    detail: item.detail ?? undefined,
    documentation: item.documentation ?? undefined,
    insertText: item.label,
    range:
      item.replacement === null
        ? new monaco.Range(
            position.lineNumber,
            position.column,
            position.lineNumber,
            position.column,
          )
        : toMonacoRange(monaco, item.replacement),
  };
}

function toMonacoCompletionKind(
  monaco: MonacoApi,
  kind: BrowserCompletionKind | null,
): Monaco.languages.CompletionItemKind {
  const kinds: Record<
    BrowserCompletionKind,
    Monaco.languages.CompletionItemKind
  > = {
    keyword: monaco.languages.CompletionItemKind.Keyword,
    annotation: monaco.languages.CompletionItemKind.Snippet,
    module: monaco.languages.CompletionItemKind.Module,
    class: monaco.languages.CompletionItemKind.Class,
    property: monaco.languages.CompletionItemKind.Property,
    reference: monaco.languages.CompletionItemKind.Reference,
    value: monaco.languages.CompletionItemKind.Value,
  };
  return kind === null
    ? monaco.languages.CompletionItemKind.Text
    : kinds[kind];
}

function toMonacoRange(
  monaco: MonacoApi,
  range: BrowserLanguageRange,
): Monaco.Range {
  return new monaco.Range(
    range.start.line + 1,
    range.start.character + 1,
    range.end.line + 1,
    range.end.character + 1,
  );
}
