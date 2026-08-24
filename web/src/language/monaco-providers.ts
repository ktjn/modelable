import type * as Monaco from 'monaco-editor/esm/vs/editor/editor.api.js';

import type {
  BrowserCompletion,
  BrowserCompletionKind,
  BrowserLanguagePositionValue,
  BrowserLanguageRange,
  BrowserTextEdit,
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
  monaco.languages.setMonarchTokensProvider('modelable', {
    defaultToken: '',
    tokenPostfix: '.mdl',

    keywords: [
      'domain',
      'owner',
      'contact',
      'description',
      'evolves',
      'add',
      'entity',
      'aggregate',
      'event',
      'value',
      'additive',
      'breaking',
      'constraint',
      'true',
      'false',
      'replacedBy',
      'union',
      'projection',
      'pick',
      'omit',
      'from',
      'as',
      'where',
      'left',
      'cardinality',
      'join',
      'on',
      'group',
      'by',
      'subscription',
      'materialisation',
      'reserved',
      'protobuf',
      'numbers',
      'names',
      'api',
      'operation',
      'method',
      'path',
      'request',
      'responses',
      'GET',
      'POST',
      'PUT',
      'PATCH',
      'DELETE',
      'generate',
      'openapi',
      'typescript',
      'avro',
      'sql',
      'jsonschema',
      'asyncapi',
      'docs',
      'postgres',
      'mysql',
      'clickhouse',
      'sqlite',
      'binding',
      'adapter',
      'model',
      'table',
      'workspace',
      'name',
      'registry',
      'package',
      'include',
      'peers',
      'ai',
      'provider',
      'repair_attempts',
      'import',
      'at',
      'consumer',
      'auto',
      'projections',
      'semantic',
      'index',
      'primary',
      'secondary',
      'key',
      'sort',
      'unique',
      'asc',
      'desc',
      'db',
      'reply',
      'exclude',
      'access',
      'property',
      'read',
      'project',
      'subscribe',
      'write',
      'transfer',
      'manage_access',
      'derive',
      'redact',
    ],

    types: [
      'string',
      'int',
      'float',
      'bool',
      'date',
      'time',
      'timestamp',
      'uuid',
      'duration',
      'binary',
      'json',
      'u8',
      'u16',
      'u32',
      'u64',
      'u128',
      'i8',
      'i16',
      'i32',
      'i64',
      'i128',
      'decimal',
      'enum',
      'array',
      'map',
      'ref',
      'object',
    ],

    operators: ['=', '<-', '->', ':', '?', ',', '.', '@', '#', '>=', '<='],

    symbols: /[=><!~?:&|+\-*\/\^%]+/,

    tokenizer: {
      root: [
        [
          /[a-zA-Z_][\w-]*/,
          {
            cases: {
              '@keywords': 'keyword',
              '@types': 'type',
              '@default': 'identifier',
            },
          },
        ],

        { include: '@whitespace' },

        [/[{}()\[\]]/, '@brackets'],
        [/[<>](?!@symbols)/, '@brackets'],
        [
          /@symbols/,
          {
            cases: {
              '@operators': 'operator',
              '@default': '',
            },
          },
        ],

        [/@\w+/, 'tag'],

        [/\d*\.\d+([eE][\-+]?\d+)?/, 'number.float'],
        [/\d+/, 'number'],

        [/[;,.]/, 'delimiter'],

        [/"/, { token: 'string.quote', bracket: '@open', next: '@string' }],
      ],

      string: [
        [/[^\\"]+/, 'string'],
        [/\\./, 'string.escape'],
        [/"/, { token: 'string.quote', bracket: '@close', next: '@pop' }],
      ],

      whitespace: [
        [/[ \t\r\n]+/, 'white'],
        [/\/\/.*$/, 'comment'],
      ],
    },
  });
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
  const definitionProvider = monaco.languages.registerDefinitionProvider(
    'modelable',
    {
      async provideDefinition(model, position, token) {
        const captured = getWorkspace();
        const result = await controller.definition(
          captured,
          model.uri.toString(),
          fromMonacoPosition(position),
        );
        if (
          token.isCancellationRequested ||
          result === undefined ||
          result.location === null
        ) {
          return null;
        }
        return {
          uri: monaco.Uri.parse(result.location.uri),
          range: toMonacoRange(monaco, result.location.range),
        };
      },
    },
  );
  const referenceProvider = monaco.languages.registerReferenceProvider(
    'modelable',
    {
      async provideReferences(model, position, context, token) {
        const captured = getWorkspace();
        const result = await controller.references(
          captured,
          model.uri.toString(),
          fromMonacoPosition(position),
          context.includeDeclaration,
        );
        if (token.isCancellationRequested || result === undefined) {
          return null;
        }
        return result.locations.map((location) => ({
          uri: monaco.Uri.parse(location.uri),
          range: toMonacoRange(monaco, location.range),
        }));
      },
    },
  );
  const renameProvider = monaco.languages.registerRenameProvider('modelable', {
    async provideRenameEdits(model, position, newName, token) {
      const captured = getWorkspace();
      const result = await controller.rename(
        captured,
        model.uri.toString(),
        fromMonacoPosition(position),
        newName,
      );
      if (token.isCancellationRequested || result === undefined) {
        return null;
      }
      return toMonacoWorkspaceEdit(monaco, result.edit.edits);
    },
    async resolveRenameLocation(model, position, token) {
      const captured = getWorkspace();
      const result = await controller.prepareRename(
        captured,
        model.uri.toString(),
        fromMonacoPosition(position),
      );
      if (token.isCancellationRequested || result === undefined) {
        return { range: new monaco.Range(1, 1, 1, 1), text: '' };
      }
      if (result.prepared === null) {
        return {
          range: new monaco.Range(1, 1, 1, 1),
          text: '',
          rejectReason: 'This element cannot be renamed.',
        };
      }
      return {
        range: toMonacoRange(monaco, result.prepared.range),
        text: result.prepared.placeholder,
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
      definitionProvider.dispose();
      referenceProvider.dispose();
      renameProvider.dispose();
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

function toMonacoWorkspaceEdit(
  monaco: MonacoApi,
  edits: BrowserTextEdit[],
): Monaco.languages.WorkspaceEdit {
  return {
    edits: edits.map((edit) => ({
      resource: monaco.Uri.parse(edit.uri),
      textEdit: {
        range: toMonacoRange(monaco, edit.range),
        text: edit.new_text,
      },
      versionId: undefined,
    })),
  };
}
