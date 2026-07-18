import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';

const {
  ConversationClient,
  recoverSessionMetadata,
  resolveConversationContext,
} = require('../../../conversationClient');
const {
  registerConversationParticipant,
} = require('../../../conversationParticipant');

suite('Modelable conversation participant', () => {
  test('manifest contributes the native chat participant', () => {
    const manifest = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '../../../package.json'), 'utf8'),
    );
    const participant = manifest.contributes.chatParticipants.find(
      (item: { id: string }) => item.id === 'modelable-vscode.modelable',
    );

    assert.ok(participant);
    assert.strictEqual(participant.name, 'modelable');
    assert.deepStrictEqual(
      participant.commands.map((item: { name: string }) => item.name),
      ['help', 'apply', 'discard', 'reset'],
    );
    assert.ok(
      manifest.activationEvents.includes(
        'onChatParticipant:modelable-vscode.modelable',
      ),
    );
  });

  test('recovers only compatible Modelable session metadata', () => {
    const compatible = {
      protocolVersion: 1,
      sessionId: 'session-1',
      workspaceUri: 'file:///workspace',
      changeSetId: 'change-1',
      kind: 'preview',
    };

    assert.deepStrictEqual(
      recoverSessionMetadata([
        { result: { metadata: { unrelated: true } } },
        { result: { metadata: { modelable: compatible } } },
      ]),
      compatible,
    );
    assert.strictEqual(
      recoverSessionMetadata([
        {
          result: {
            metadata: {
              modelable: {
                protocolVersion: 2,
                sessionId: 'future',
                workspaceUri: 'file:///workspace',
              },
            },
          },
        },
      ]),
      undefined,
    );
  });

  test('active model selects its folder and reports only dirty models there', async () => {
    const api = fakeVscode({
      folders: ['/workspace', '/other'],
      active: '/workspace/customer.mdl',
      documents: [
        { path: '/workspace/customer.mdl', languageId: 'mdl', isDirty: true },
        { path: '/workspace/notes.txt', languageId: 'plaintext', isDirty: true },
        { path: '/other/order.mdl', languageId: 'mdl', isDirty: true },
      ],
    });

    const context = await resolveConversationContext(api);

    assert.strictEqual(context.workspaceUri.toString(), 'file:///workspace');
    assert.strictEqual(
      context.activeDocumentUri.toString(),
      'file:///workspace/customer.mdl',
    );
    assert.deepStrictEqual(
      context.dirtyDocumentUris.map((uri: FakeUri) => uri.toString()),
      ['file:///workspace/customer.mdl'],
    );
    assert.deepStrictEqual(context.position, { line: 3, character: 8 });
  });

  test('one manifest folder is selected without an active model', async () => {
    const api = fakeVscode({
      folders: ['/workspace', '/other'],
      manifests: ['/other/workspace.mdl'],
    });

    const context = await resolveConversationContext(api);

    assert.strictEqual(context.workspaceUri.toString(), 'file:///other');
    assert.strictEqual(context.activeDocumentUri, undefined);
  });

  test('reports ambiguous and missing workspace context', async () => {
    const ambiguous = fakeVscode({
      folders: ['/workspace', '/other'],
      manifests: ['/workspace/workspace.mdl', '/other/workspace.mdl'],
    });
    const missing = fakeVscode({ folders: ['/workspace'] });

    await assert.rejects(
      () => resolveConversationContext(ambiguous),
      /multiple Modelable workspaces/i,
    );
    await assert.rejects(
      () => resolveConversationContext(missing),
      /open a Modelable file/i,
    );
  });

  test('participant streams replies and returns namespaced metadata', async () => {
    let handler: Function | undefined;
    const participant = { dispose() {} };
    const vscodeApi = {
      chat: {
        createChatParticipant: (id: string, value: Function) => {
          assert.strictEqual(id, 'modelable-vscode.modelable');
          handler = value;
          return participant;
        },
      },
    };
    const conversationClient = {
      turn: async () => ({
        kind: 'answer',
        text: 'Workspace validation passed.',
        sessionId: 'session-1',
        workspaceUri: 'file:///workspace',
        changeSetId: null,
      }),
    };
    const initializeResult = {
      capabilities: {
        experimental: {
          modelableConversation: { protocolVersion: 1 },
        },
      },
    };
    const streamed: string[] = [];

    assert.strictEqual(
      registerConversationParticipant(
        vscodeApi,
        conversationClient,
        initializeResult,
      ),
      participant,
    );
    assert.ok(handler);
    const result = await handler!(
      { prompt: 'is the workspace valid?' },
      { history: [] },
      { markdown: (value: string) => streamed.push(value) },
      {},
    );

    assert.deepStrictEqual(streamed, ['Workspace validation passed.']);
    assert.deepStrictEqual(result.metadata.modelable, {
      protocolVersion: 1,
      sessionId: 'session-1',
      workspaceUri: 'file:///workspace',
      changeSetId: null,
      kind: 'answer',
    });
  });

  test('participant reports capability and request failures as chat errors', async () => {
    const handlers: Function[] = [];
    const vscodeApi = {
      chat: {
        createChatParticipant: (_id: string, handler: Function) => {
          handlers.push(handler);
          return { dispose() {} };
        },
      },
    };
    registerConversationParticipant(
      vscodeApi,
      { turn: async () => assert.fail('turn should not be called') },
      { capabilities: {} },
    );
    const capabilityResult = await handlers[0](
      { prompt: 'hello' },
      { history: [] },
      { markdown() {} },
      {},
    );

    assert.match(capabilityResult.errorDetails.message, /upgrade.*language server/i);

    registerConversationParticipant(
      vscodeApi,
      { turn: async () => { throw new Error('Save these files: customer.mdl'); } },
      {
        capabilities: {
          experimental: {
            modelableConversation: { protocolVersion: 1 },
          },
        },
      },
    );
    const requestResult = await handlers[1](
      { prompt: 'update customer' },
      { history: [] },
      { markdown() {} },
      {},
    );

    assert.match(requestResult.errorDetails.message, /save these files/i);
  });

  test('conversation client sends exact turn and lifecycle payloads', async () => {
    const calls: Array<{ method: string; payload: any; token?: object }> = [];
    const languageClient = {
      sendRequest: async (method: string, payload: any, token?: object) => {
        calls.push({ method, payload, token });
        return {
          kind: 'answer',
          text: 'valid',
          sessionId: payload.sessionId,
          workspaceUri: 'file:///workspace',
        };
      },
    };
    const api = fakeVscode({
      folders: ['/workspace'],
      active: '/workspace/customer.mdl',
    });
    const client = new ConversationClient(
      languageClient,
      api,
      () => 'generated-session',
    );
    const token = {};

    await client.turn(
      { prompt: 'is the workspace valid?' },
      { history: [] },
      token,
    );

    assert.deepStrictEqual(calls[0], {
      method: 'modelable/conversation/turn',
      payload: {
        protocolVersion: 1,
        sessionId: 'generated-session',
        createSession: true,
        workspaceUri: 'file:///workspace',
        message: 'is the workspace valid?',
        activeDocumentUri: 'file:///workspace/customer.mdl',
        position: { line: 3, character: 8 },
        dirtyDocumentUris: [],
      },
      token,
    });

    const metadata = {
      protocolVersion: 1,
      sessionId: 'generated-session',
      workspaceUri: 'file:///workspace',
      changeSetId: 'change-1',
    };
    await client.apply(metadata, [new FakeUri('/workspace/customer.mdl')], token);
    await client.discard(metadata, token);
    await client.closeAll();

    assert.deepStrictEqual(
      calls.slice(1).map(call => [call.method, call.payload]),
      [
        [
          'modelable/conversation/apply',
          {
            protocolVersion: 1,
            sessionId: 'generated-session',
            changeSetId: 'change-1',
            dirtyDocumentUris: ['file:///workspace/customer.mdl'],
          },
        ],
        [
          'modelable/conversation/discard',
          {
            protocolVersion: 1,
            sessionId: 'generated-session',
            changeSetId: 'change-1',
            dirtyDocumentUris: [],
          },
        ],
        [
          'modelable/conversation/close',
          {
            protocolVersion: 1,
            sessionId: 'generated-session',
          },
        ],
      ],
    );
  });

  test('recovered sessions cannot silently switch workspaces', async () => {
    const languageClient = {
      sendRequest: async () => assert.fail('request should not be sent'),
    };
    const client = new ConversationClient(
      languageClient,
      fakeVscode({
        folders: ['/workspace', '/other'],
        active: '/other/order.mdl',
      }),
      () => 'unused',
    );

    await assert.rejects(
      () => client.turn(
        { prompt: 'describe it' },
        {
          history: [{
            result: {
              metadata: {
                modelable: {
                  protocolVersion: 1,
                  sessionId: 'session-1',
                  workspaceUri: 'file:///workspace',
                },
              },
            },
          }],
        },
        {},
      ),
      /reset.*new chat/i,
    );
  });
});

class FakeUri {
  constructor(readonly fsPath: string) {}

  get scheme(): string {
    return 'file';
  }

  get path(): string {
    return this.fsPath;
  }

  toString(): string {
    return `file://${this.fsPath}`;
  }
}

function fakeVscode(options: {
  folders: string[];
  active?: string;
  documents?: Array<{ path: string; languageId: string; isDirty: boolean }>;
  manifests?: string[];
}) {
  const folders = options.folders.map(folderPath => ({
    uri: new FakeUri(folderPath),
    name: path.basename(folderPath),
  }));
  const documentFor = (
    documentPath: string,
    languageId = 'mdl',
    isDirty = false,
  ) => ({
    uri: new FakeUri(documentPath),
    languageId,
    isDirty,
  });
  const activeDocument = options.active
    ? documentFor(options.active)
    : undefined;
  const manifests = new Set(options.manifests ?? []);
  const getWorkspaceFolder = (uri: FakeUri) =>
    folders
      .filter(folder => (
        uri.fsPath === folder.uri.fsPath ||
        uri.fsPath.startsWith(`${folder.uri.fsPath}/`)
      ))
      .sort((left, right) => right.uri.fsPath.length - left.uri.fsPath.length)[0];

  return {
    Uri: {
      joinPath: (base: FakeUri, ...segments: string[]) =>
        new FakeUri(path.posix.join(base.fsPath, ...segments)),
    },
    window: {
      activeTextEditor: activeDocument
        ? {
            document: activeDocument,
            selection: { active: { line: 3, character: 8 } },
          }
        : undefined,
    },
    workspace: {
      workspaceFolders: folders,
      textDocuments: (options.documents ?? []).map(document =>
        documentFor(document.path, document.languageId, document.isDirty),
      ),
      getWorkspaceFolder,
      fs: {
        stat: async (uri: FakeUri) => {
          if (!manifests.has(uri.fsPath)) {
            throw new Error('not found');
          }
          return {};
        },
      },
    },
  };
}
