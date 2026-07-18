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
  renderReply,
} = require('../../../conversationParticipant');
const {
  PreviewStore,
} = require('../../../conversationPreview');

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
    assert.ok(
      manifest.contributes.commands.some(
        (item: { command: string }) =>
          item.command === 'modelable.conversation.viewDiff',
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

  test('preview store retains exact before and after snapshots', () => {
    const store = new PreviewStore(fakeVscode({ folders: [] }));
    const keys = store.put('session-1', 'change-1', [
      {
        uri: 'file:///workspace/customer.mdl',
        existedBefore: true,
        beforeText: 'before',
        afterText: 'after',
      },
    ]);

    assert.strictEqual(
      store.provideTextDocumentContent(keys[0].beforeUri),
      'before',
    );
    assert.strictEqual(
      store.provideTextDocumentContent(keys[0].afterUri),
      'after',
    );
    store.deleteChangeSet('session-1', 'change-1');
    assert.strictEqual(
      store.provideTextDocumentContent(keys[0].afterUri),
      undefined,
    );
  });

  test('preview store represents a new file with an empty before snapshot', () => {
    const store = new PreviewStore(fakeVscode({ folders: [] }));
    const [descriptor] = store.put('session-1', 'change-1', [
      {
        uri: 'file:///workspace/address.mdl',
        existedBefore: false,
        beforeText: '',
        afterText: 'domain address {}',
      },
    ]);

    assert.strictEqual(
      store.provideTextDocumentContent(descriptor.beforeUri),
      '',
    );
  });

  test('structured preview rendering caches snapshots, anchors refs, and adds one safe button', () => {
    const markdown: string[] = [];
    const anchors: Array<[string, string]> = [];
    const buttons: any[] = [];
    const puts: any[] = [];
    const stream = {
      markdown: (value: string) => markdown.push(value),
      anchor: (uri: FakeUri, label: string) =>
        anchors.push([uri.toString(), label]),
      button: (button: any) => buttons.push(button),
    };
    const previewStore = {
      put: (...args: any[]) => puts.push(args),
    };
    const reply = {
      kind: 'preview',
      text: 'Canonical preview',
      sessionId: 'session-1',
      changeSetId: 'change-1',
      changedDefinitions: [{
        ref: 'customer.Customer@1',
        location: { uri: 'file:///workspace/customer.mdl' },
      }],
      affectedDefinitions: [{
        ref: 'billing.Bill@1',
        location: { uri: 'file:///workspace/billing.mdl' },
      }],
      previewFiles: [{
        uri: 'file:///workspace/customer.mdl',
        existedBefore: true,
        beforeText: 'before',
        afterText: 'after',
      }],
    };

    renderReply(
      reply,
      stream,
      fakeVscode({ folders: [] }),
      previewStore,
    );

    assert.deepStrictEqual(markdown, ['Canonical preview']);
    assert.deepStrictEqual(anchors, [
      ['file:///workspace/customer.mdl', 'customer.Customer@1'],
      ['file:///workspace/billing.mdl', 'billing.Bill@1'],
    ]);
    assert.strictEqual(puts.length, 1);
    assert.strictEqual(buttons.length, 1);
    assert.deepStrictEqual(buttons[0], {
      command: 'modelable.conversation.viewDiff',
      title: 'View Diff',
      arguments: [{
        sessionId: 'session-1',
        changeSetId: 'change-1',
      }],
    });
    assert.strictEqual(
      JSON.stringify(buttons[0]).includes('before'),
      false,
    );
  });

  test('plain answers do not cache preview content', () => {
    const previewStore = {
      put: () => assert.fail('plain replies must not register snapshots'),
    };

    renderReply(
      {
        kind: 'answer',
        text: 'Grounded answer',
        changedDefinitions: [],
        affectedDefinitions: [],
        previewFiles: [],
      },
      { markdown() {}, anchor() {}, button() {} },
      fakeVscode({ folders: [] }),
      previewStore,
    );
  });

  test('preview results offer native apply and discard followups', () => {
    const participant: any = { dispose() {} };
    const vscodeApi = {
      chat: {
        createChatParticipant: () => participant,
      },
    };
    registerConversationParticipant(
      vscodeApi,
      { turn: async () => undefined },
      {
        capabilities: {
          experimental: {
            modelableConversation: { protocolVersion: 1 },
          },
        },
      },
    );

    assert.deepStrictEqual(
      participant.followupProvider.provideFollowups({
        metadata: {
          modelable: {
            protocolVersion: 1,
            kind: 'preview',
            sessionId: 'session-1',
            workspaceUri: 'file:///workspace',
            changeSetId: 'change-1',
          },
        },
      }),
      [
        {
          prompt: '',
          label: 'Apply change set',
          participant: 'modelable-vscode.modelable',
          command: 'apply',
        },
        {
          prompt: '',
          label: 'Discard',
          participant: 'modelable-vscode.modelable',
          command: 'discard',
        },
      ],
    );
    assert.deepStrictEqual(
      participant.followupProvider.provideFollowups({
        metadata: { modelable: { kind: 'answer' } },
      }),
      [],
    );
  });

  test('apply, discard, and reset route exact metadata and clean successful previews', async () => {
    let handler: Function | undefined;
    const vscodeApi = {
      Uri: {
        parse: (value: string) => new FakeUri(value.slice('file://'.length)),
      },
      chat: {
        createChatParticipant: (_id: string, value: Function) => {
          handler = value;
          return { dispose() {} };
        },
      },
    };
    const calls: any[] = [];
    const conversationClient = {
      dirtyDocumentUris: (workspaceUri: string) => {
        calls.push(['dirty', workspaceUri]);
        return [new FakeUri('/workspace/customer.mdl')];
      },
      apply: async (metadata: any, dirty: FakeUri[], token: object) => {
        calls.push(['apply', metadata, dirty, token]);
        return {
          kind: 'applied',
          text: 'Applied.',
          sessionId: metadata.sessionId,
          workspaceUri: metadata.workspaceUri,
          changeSetId: metadata.changeSetId,
        };
      },
      discard: async (metadata: any, token: object) => {
        calls.push(['discard', metadata, token]);
        return {
          kind: 'discarded',
          text: 'Discarded.',
          sessionId: metadata.sessionId,
          workspaceUri: metadata.workspaceUri,
          changeSetId: metadata.changeSetId,
        };
      },
      close: async (sessionId: string) => {
        calls.push(['close', sessionId]);
      },
    };
    const deleted: any[] = [];
    const previewStore = {
      deleteChangeSet: (...args: any[]) => deleted.push(['change', ...args]),
      deleteSession: (...args: any[]) => deleted.push(['session', ...args]),
    };
    registerConversationParticipant(
      vscodeApi,
      conversationClient,
      {
        capabilities: {
          experimental: {
            modelableConversation: { protocolVersion: 1 },
          },
        },
      },
      previewStore,
    );
    assert.ok(handler);
    const metadata = {
      protocolVersion: 1,
      sessionId: 'session-1',
      workspaceUri: 'file:///workspace',
      changeSetId: 'change-1',
      kind: 'preview',
    };
    const context = {
      history: [{ result: { metadata: { modelable: metadata } } }],
    };
    const stream = { markdown() {}, anchor() {}, button() {} };
    const token = {};

    await handler!({ command: 'apply', prompt: '' }, context, stream, token);
    await handler!({ command: 'discard', prompt: '' }, context, stream, token);
    const reset = await handler!(
      { command: 'reset', prompt: '' },
      context,
      stream,
      token,
    );

    assert.deepStrictEqual(calls, [
      ['dirty', 'file:///workspace'],
      [
        'apply',
        metadata,
        [new FakeUri('/workspace/customer.mdl')],
        token,
      ],
      ['discard', metadata, token],
      ['close', 'session-1'],
    ]);
    assert.deepStrictEqual(deleted, [
      ['change', 'session-1', 'change-1'],
      ['change', 'session-1', 'change-1'],
      ['session', 'session-1'],
    ]);
    assert.strictEqual(
      Object.prototype.hasOwnProperty.call(
        reset.metadata.modelable,
        'sessionId',
      ),
      false,
    );
  });

  test('failed apply retains cached preview content', async () => {
    let handler: Function | undefined;
    const previewStore = {
      deleteChangeSet: () => assert.fail('failed apply must retain preview'),
    };
    registerConversationParticipant(
      {
        chat: {
          createChatParticipant: (_id: string, value: Function) => {
            handler = value;
            return { dispose() {} };
          },
        },
      },
      {
        dirtyDocumentUris: () => [],
        apply: async () => {
          throw new Error('Change set old-id is not the current pending change set.');
        },
      },
      {
        capabilities: {
          experimental: {
            modelableConversation: { protocolVersion: 1 },
          },
        },
      },
      previewStore,
    );
    const result = await handler!(
      { command: 'apply', prompt: '' },
      {
        history: [{
          result: {
            metadata: {
              modelable: {
                protocolVersion: 1,
                sessionId: 'session-1',
                workspaceUri: 'file:///workspace',
                changeSetId: 'old-id',
              },
            },
          },
        }],
      },
      { markdown() {}, anchor() {}, button() {} },
      {},
    );

    assert.match(result.errorDetails.message, /current pending change set/i);
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
      parse: (value: string) => (
        value.startsWith('file://')
          ? new FakeUri(value.slice('file://'.length))
          : new FakeUri(value)
      ),
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
