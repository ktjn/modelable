import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';

const {
  ConversationClient,
  isFileUriInsideWorkspace,
  recoverSessionMetadata,
  resolveConversationContext,
} = require('../../../conversationClient');
const {
  chatResult,
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
      protocolVersion: 2,
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
                protocolVersion: 3,
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

  test('active model selects its folder and reports every dirty file there', async () => {
    const api = fakeVscode({
      folders: ['/workspace', '/workspace/dist', '/other'],
      active: '/workspace/customer.mdl',
      documents: [
        { path: '/workspace/customer.mdl', languageId: 'mdl', isDirty: true },
        { path: '/workspace/notes.txt', languageId: 'plaintext', isDirty: true },
        {
          path: '/workspace/dist/rust/customer.rs',
          languageId: 'rust',
          isDirty: true,
        },
        {
          path: '/workspace/virtual.txt',
          languageId: 'plaintext',
          isDirty: true,
          scheme: 'untitled',
        },
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
      [
        'file:///workspace/customer.mdl',
        'file:///workspace/dist/rust/customer.rs',
        'file:///workspace/notes.txt',
      ],
    );
    assert.deepStrictEqual(context.position, { line: 3, character: 8 });
  });

  test('workspace containment canonicalizes missing descendants without admitting symlink escapes', () => {
    const root = path.resolve(path.parse(process.cwd()).root, 'virtual', 'link');
    const realRoot = path.resolve(path.parse(process.cwd()).root, 'virtual', 'real');
    const outside = path.resolve(path.parse(process.cwd()).root, 'virtual', 'outside');
    const generated = path.join(root, 'dist', 'new.rs');
    const escaped = path.join(root, 'escape', 'new.rs');
    const lexicalEscape = path.join(root, '..', 'outside', 'new.rs');
    const sibling = path.resolve(`${root}-sibling`, 'new.rs');
    const canonical = new Map([
      [root, realRoot],
      [path.join(root, 'escape'), outside],
    ]);
    const calls: string[] = [];
    const realpath = (value: string) => {
      const resolved = path.resolve(value);
      calls.push(resolved);
      const result = canonical.get(resolved);
      if (!result) {
        throw new Error('missing');
      }
      return result;
    };
    const api = fakeVscode({ folders: [] });
    const workspaceUri = new FakeUri(root).toString();

    assert.strictEqual(
      isFileUriInsideWorkspace(
        api,
        workspaceUri,
        new FakeUri(generated),
        realpath,
      ),
      true,
    );
    assert.strictEqual(
      isFileUriInsideWorkspace(
        api,
        workspaceUri,
        new FakeUri(escaped),
        realpath,
      ),
      false,
    );
    assert.strictEqual(
      isFileUriInsideWorkspace(
        api,
        workspaceUri,
        new FakeUri(lexicalEscape),
        realpath,
      ),
      false,
    );
    assert.strictEqual(
      isFileUriInsideWorkspace(
        api,
        workspaceUri,
        new FakeUri(sibling),
        realpath,
      ),
      false,
    );
    assert.ok(calls.includes(path.join(root, 'dist')));
    assert.ok(calls.includes(root));
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
          modelableConversation: { protocolVersion: 2 },
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
      protocolVersion: 2,
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
            modelableConversation: { protocolVersion: 2 },
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

    registerConversationParticipant(
      vscodeApi,
      { turn: async () => assert.fail('version 3 must not send a request') },
      {
        capabilities: {
          experimental: {
            modelableConversation: { protocolVersion: 3 },
          },
        },
      },
    );
    const futureResult = await handlers[2](
      { prompt: 'hello' },
      { history: [] },
      { markdown() {} },
      {},
    );
    assert.match(futureResult.errorDetails.message, /upgrade.*language server/i);
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
    const api: any = fakeVscode({
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
        protocolVersion: 2,
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
      protocolVersion: 2,
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
            protocolVersion: 2,
            sessionId: 'generated-session',
            changeSetId: 'change-1',
            dirtyDocumentUris: ['file:///workspace/customer.mdl'],
          },
        ],
        [
          'modelable/conversation/discard',
          {
            protocolVersion: 2,
            sessionId: 'generated-session',
            changeSetId: 'change-1',
            dirtyDocumentUris: [],
          },
        ],
        [
          'modelable/conversation/close',
          {
            protocolVersion: 2,
            sessionId: 'generated-session',
          },
        ],
      ],
    );
    assert.strictEqual(
      calls[1].token,
      undefined,
      'native Apply must not attach a cancellation token after authorization',
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
                  protocolVersion: 2,
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

  test('compile preview stores generated text snapshots and renders operational details', () => {
    const markdown: string[] = [];
    const anchors: Array<[string, string]> = [];
    const buttons: any[] = [];
    const store = new PreviewStore(fakeVscode({ folders: [] }));
    const reply = {
      protocolVersion: 2,
      kind: 'preview',
      operationKind: 'compile',
      text: 'Compile customer to Rust.',
      sessionId: 'session-1',
      workspaceUri: 'file:///workspace',
      changeSetId: 'compile-1',
      changedDefinitions: [],
      affectedDefinitions: [{
        ref: 'customer.Customer@1',
        status: 'affected',
        reason: 'Generates the Rust customer type.',
        location: { uri: 'file:///workspace/customer.mdl' },
      }],
      previewFiles: [],
      compilationFiles: [
        {
          category: 'artifact',
          uri: 'file:///workspace/dist/rust/customer.rs',
          status: 'created',
          mediaType: 'text/x-rust',
          ref: 'customer.Customer@1',
          beforeHash: null,
          afterHash: 'text-hash',
          beforeSize: 0,
          afterSize: 24,
          beforeText: '',
          afterText: 'pub struct Customer {}',
          diffText: '--- before\n+++ after\n',
        },
        {
          category: 'registry',
          uri: 'file:///workspace/.modelable/registry.db',
          status: 'changed',
          mediaType: 'application/vnd.sqlite3',
          ref: null,
          beforeHash: 'old-hash',
          afterHash: 'binary-hash',
          beforeSize: 2048,
          afterSize: 4096,
          beforeText: null,
          afterText: null,
          diffText: null,
        },
        {
          category: 'artifact',
          uri: 'file:///workspace/dist/schema.json',
          status: 'unchanged',
          mediaType: 'application/json',
          ref: null,
          beforeHash: 'json-hash',
          afterHash: 'json-hash',
          beforeSize: 20,
          afterSize: 20,
          beforeText: null,
          afterText: null,
          diffText: null,
        },
        {
          category: 'plan',
          uri: 'file:///workspace/.modelable/plans/customer.yaml',
          status: 'unchanged',
          mediaType: 'application/yaml',
          ref: null,
          beforeHash: 'yaml-hash',
          afterHash: 'yaml-hash',
          beforeSize: 30,
          afterSize: 30,
          beforeText: null,
          afterText: null,
          diffText: null,
        },
        {
          category: 'artifact',
          uri: 'file:///workspace/dist/rust/unchanged.rs',
          status: 'unchanged',
          mediaType: 'text/x-rust',
          ref: null,
          beforeHash: 'rust-hash',
          afterHash: 'rust-hash',
          beforeSize: 40,
          afterSize: 40,
          beforeText: null,
          afterText: null,
          diffText: null,
        },
      ],
      registryIdChanges: [{
        ref: 'customer.SchemaId',
        registryId: 17,
      }],
      auditUri: null,
    };
    const stream = {
      markdown: (value: string) => markdown.push(value),
      anchor: (uri: FakeUri, label: string) =>
        anchors.push([uri.toString(), label]),
      button: (button: any) => buttons.push(button),
    };

    renderReply(reply, stream, fakeVscode({ folders: [] }), store);

    assert.deepStrictEqual(buttons, [{
      command: 'modelable.conversation.viewDiff',
      title: 'View generated diffs',
      arguments: [{ sessionId: 'session-1', changeSetId: 'compile-1' }],
    }]);
    assert.deepStrictEqual(anchors, [
      ['file:///workspace/customer.mdl', 'customer.Customer@1'],
    ]);
    assert.match(markdown.join('\n'), /registry\.db.*SHA-256.*binary-hash/is);
    assert.match(markdown.join('\n'), /registry.*changed.*registry\.db/is);
    assert.match(markdown.join('\n'), /customer\.SchemaId.*17/s);
    assert.doesNotMatch(
      markdown.join('\n'),
      /Binary.*(?:schema\.json|customer\.yaml|unchanged\.rs)/is,
    );
    const descriptors = store.changeSets.get('session-1\0compile-1');
    assert.strictEqual(descriptors.length, 1);
    assert.match(descriptors[0].beforeUri.toString(), /before\.rs$/);
    assert.match(descriptors[0].afterUri.toString(), /after\.rs$/);
    assert.strictEqual(
      store.provideTextDocumentContent(descriptors[0].afterUri),
      'pub struct Customer {}',
    );
  });

  test('compile preview offers multiple generated diffs and applied audit link', async () => {
    const picked: string[] = [];
    const commands: any[] = [];
    const api: any = fakeVscode({ folders: [] });
    api.window.showQuickPick = async (items: any[]) => {
      picked.push(...items.map(item => item.label));
      return items[1];
    };
    api.commands = {
      executeCommand: async (...args: any[]) => commands.push(args),
    };
    const store = new PreviewStore(api);
    store.put('session-1', 'compile-1', [
      {
        uri: 'file:///workspace/dist/rust/customer.rs',
        existedBefore: false,
        beforeText: '',
        afterText: 'customer',
      },
      {
        uri: 'file:///workspace/dist/rust/order.rs',
        existedBefore: true,
        beforeText: 'old order',
        afterText: 'new order',
      },
    ]);

    await store.showDiff('session-1', 'compile-1');

    assert.deepStrictEqual(picked, ['customer.rs', 'order.rs']);
    assert.strictEqual(commands[0][0], 'vscode.diff');
    assert.match(commands[0][1].toString(), /before\.rs$/);
    assert.match(commands[0][2].toString(), /after\.rs$/);

    const anchors: Array<[string, string]> = [];
    renderReply(
      {
        kind: 'applied',
        operationKind: 'compile',
        text: 'Applied compilation.',
        sessionId: 'session-1',
        workspaceUri: 'file:///workspace',
        changeSetId: 'compile-1',
        auditUri: 'file:///workspace/.modelable/audit/compilations/compile-1.json',
      },
      {
        markdown() {},
        anchor: (uri: FakeUri, label: string) =>
          anchors.push([uri.toString(), label]),
        button() {},
      },
      api,
      store,
    );
    assert.deepStrictEqual(anchors, [[
      'file:///workspace/.modelable/audit/compilations/compile-1.json',
      'View compilation audit',
    ]]);
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
            modelableConversation: { protocolVersion: 2 },
          },
        },
      },
    );

    assert.deepStrictEqual(
      participant.followupProvider.provideFollowups({
        metadata: {
          modelable: {
            protocolVersion: 2,
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

    const compilationResult = chatResult({
      kind: 'preview',
      operationKind: 'compile',
      sessionId: 'session-1',
      workspaceUri: 'file:///workspace',
      changeSetId: 'compile-1',
    });
    assert.strictEqual(
      compilationResult.metadata.modelable.operationKind,
      'compile',
    );
    assert.deepStrictEqual(
      participant.followupProvider.provideFollowups(compilationResult),
      [
        {
          prompt: '',
          label: 'Apply compilation',
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
        return [new FakeUri('/workspace/dist/rust/customer.rs')];
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
            modelableConversation: { protocolVersion: 2 },
          },
        },
      },
      previewStore,
    );
    assert.ok(handler);
    const metadata = {
      protocolVersion: 2,
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
        [new FakeUri('/workspace/dist/rust/customer.rs')],
        undefined,
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
            modelableConversation: { protocolVersion: 2 },
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
                protocolVersion: 2,
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

  test('cancelled turns close and invalidate the session before the next turn', async () => {
    class FakeCancellationError extends Error {}
    const calls: any[] = [];
    let turnCount = 0;
    const languageClient = {
      sendRequest: async (method: string, payload: any) => {
        calls.push([method, payload]);
        if (method === 'modelable/conversation/turn') {
          turnCount += 1;
          if (turnCount === 1) {
            throw new FakeCancellationError('cancelled');
          }
          return {
            kind: 'answer',
            text: 'valid',
            sessionId: payload.sessionId,
            workspaceUri: payload.workspaceUri,
          };
        }
        return undefined;
      },
    };
    const api: any = fakeVscode({
      folders: ['/workspace'],
      active: '/workspace/customer.mdl',
    });
    api.CancellationError = FakeCancellationError;
    const ids = ['session-1', 'session-2'];
    const client = new ConversationClient(
      languageClient,
      api,
      () => ids.shift(),
    );

    await assert.rejects(
      () => client.turn(
        { prompt: 'first request' },
        { history: [] },
        { isCancellationRequested: true },
      ),
      FakeCancellationError,
    );
    await client.turn(
      { prompt: 'second request' },
      {
        history: [{
          result: {
            metadata: {
              modelable: {
                protocolVersion: 2,
                sessionId: 'session-1',
                workspaceUri: 'file:///workspace',
              },
            },
          },
        }],
      },
      { isCancellationRequested: false },
    );

    assert.strictEqual(calls[1][0], 'modelable/conversation/close');
    assert.strictEqual(calls[2][1].sessionId, 'session-2');
    assert.strictEqual(calls[2][1].createSession, true);
  });

  test('conversation logs contain lifecycle fields but no prompt or reply content', async () => {
    const lines: string[] = [];
    const output = { appendLine: (line: string) => lines.push(line) };
    const api = fakeVscode({
      folders: ['/workspace'],
      active: '/workspace/customer.mdl',
    });
    const client = new ConversationClient(
      {
        sendRequest: async (_method: string, payload: any) => ({
          kind: 'answer',
          text: 'diff-secret API_KEY=credential diagnostic-private',
          sessionId: payload.sessionId,
          workspaceUri: payload.workspaceUri,
        }),
      },
      api,
      () => 'session-1',
      output,
    );

    await client.turn(
      { prompt: 'prompt-private' },
      { history: [] },
      {},
    );

    const logged = lines.join('\n');
    assert.match(logged, /kind=turn/);
    assert.match(logged, /protocol=2/);
    assert.match(logged, /reply=answer/);
    assert.match(logged, /elapsedMs=\d+/);
    for (const secret of [
      'prompt-private',
      'diff-secret',
      'credential',
      'diagnostic-private',
    ]) {
      assert.strictEqual(logged.includes(secret), false);
    }
  });

  test('participant cancellation clears previews and returns no stale metadata', async () => {
    let handler: Function | undefined;
    const deleted: string[] = [];
    const error: any = new Error('cancelled');
    error.modelableSessionId = 'session-1';
    registerConversationParticipant(
      {
        CancellationError: class extends Error {},
        chat: {
          createChatParticipant: (_id: string, value: Function) => {
            handler = value;
            return { dispose() {} };
          },
        },
      },
      {
        turn: async () => { throw error; },
        forgetSession: (sessionId: string) => deleted.push(`forgot:${sessionId}`),
      },
      {
        capabilities: {
          experimental: {
            modelableConversation: { protocolVersion: 2 },
          },
        },
      },
      {
        deleteSession: (sessionId: string) => deleted.push(`preview:${sessionId}`),
      },
    );

    const result = await handler!(
      { prompt: 'slow request' },
      { history: [] },
      { markdown() {} },
      { isCancellationRequested: true },
    );

    assert.deepStrictEqual(deleted, [
      'forgot:session-1',
      'preview:session-1',
    ]);
    assert.strictEqual(result?.metadata, undefined);
  });

  test('expired recovered sessions clear previews and request a fresh turn', async () => {
    let handler: Function | undefined;
    const cleared: string[] = [];
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
        turn: async () => {
          throw new Error('Conversation session session-1 is unknown or expired.');
        },
        forgetSession: (sessionId: string) => cleared.push(`forgot:${sessionId}`),
      },
      {
        capabilities: {
          experimental: {
            modelableConversation: { protocolVersion: 2 },
          },
        },
      },
      {
        deleteSession: (sessionId: string) => cleared.push(`preview:${sessionId}`),
      },
    );

    const result = await handler!(
      { prompt: 'continue' },
      {
        history: [{
          result: {
            metadata: {
              modelable: {
                protocolVersion: 2,
                sessionId: 'session-1',
                workspaceUri: 'file:///workspace',
              },
            },
          },
        }],
      },
      { markdown() {} },
      {},
    );

    assert.deepStrictEqual(cleared, [
      'forgot:session-1',
      'preview:session-1',
    ]);
    assert.match(result.errorDetails.message, /repeat the request/i);
  });
});

class FakeUri {
  constructor(
    readonly fsPath: string,
    readonly scheme: string = 'file',
  ) {}

  get path(): string {
    return this.fsPath;
  }

  toString(): string {
    return this.scheme === 'file'
      ? `file://${this.fsPath}`
      : `${this.scheme}:${this.fsPath}`;
  }
}

function fakeVscode(options: {
  folders: string[];
  active?: string;
  documents?: Array<{
    path: string;
    languageId: string;
    isDirty: boolean;
    scheme?: string;
  }>;
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
    scheme = 'file',
  ) => ({
    uri: new FakeUri(documentPath, scheme),
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
        documentFor(
          document.path,
          document.languageId,
          document.isDirty,
          document.scheme,
        ),
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
