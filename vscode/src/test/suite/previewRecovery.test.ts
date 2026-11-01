import * as assert from 'assert';
import { spawn } from 'child_process';
import { createHash } from 'crypto';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { LanguageClient, RevealOutputChannelOn } from 'vscode-languageclient/node';
const { ConversationClient } = require('../../../conversationClient');
const { registerConversationParticipant } = require('../../../conversationParticipant');
const { PreviewStore } = require('../../../conversationPreview');

suite('Native conversation preview recovery', function () {
  this.timeout(60_000);
  for (const fault of ['malformed-ledger', 'sqlite-operational']) {
    test(`${fault}: first-turn history, preserved preview, apply and reset cross real RPC`, async () => {
      const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'modelable-preview-recovery-'));
      const workspace = path.join(temporary, 'workspace');
      const stages = path.join(temporary, 'stages');
      await fs.mkdir(workspace);
      await fs.mkdir(stages);
      const source = path.join(workspace, 'workspace.mdl');
      const sourceBytes = Buffer.from('domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }');
      await fs.writeFile(source, sourceBytes);
      const ledger = path.join(workspace, 'registry-ids.lock');
      const malformed = Buffer.from('{"broken":');
      await fs.writeFile(ledger, fault === 'malformed-ledger' ? malformed : '{}');
      const cli = path.join(path.resolve(__dirname, '../../../..'), 'cli');
      const python = process.platform === 'win32' ? path.join(cli, '.venv', 'Scripts', 'python.exe') : path.join(cli, '.venv', 'bin', 'python');
      const folder = { uri: vscode.Uri.file(workspace), name: 'preview-recovery', index: 0 };
      const output = vscode.window.createOutputChannel('Modelable preview recovery test', { log: true });
      let serverExit: Promise<void> | undefined;
      const languageClient = new LanguageClient('modelable-preview-recovery', 'Modelable preview recovery', async () => {
        const server = spawn(python, [path.join(cli, 'tests', 'support', 'lsp_preview_recovery_server.py'), stages,
          fault === 'sqlite-operational' ? 'sqlite-first-and-third' : 'none'], {
          cwd: cli, windowsHide: true, env: { ...process.env, MODELABLE_LLM_PROVIDER: '', MODELABLE_LLM_MODEL: '' },
        });
        serverExit = new Promise<void>(resolve => server.once('close', () => resolve()));
        return server;
      }, { documentSelector: [], workspaceFolder: folder, outputChannel: output, revealOutputChannelOn: RevealOutputChannelOn.Never });
      let conversation: any;
      const token = new vscode.CancellationTokenSource();
      try {
        await languageClient.start();
        const calls: { method: string; params: any; reply?: any }[] = [];
        const wireErrors: { method: string; message: string }[] = [];
        const transport = { async sendRequest(method: string, params: any, cancellation?: vscode.CancellationToken) {
          const call: { method: string; params: any; reply?: any } = { method, params };
          calls.push(call);
          try {
            call.reply = cancellation === undefined
              ? await languageClient.sendRequest(method, params)
              : await languageClient.sendRequest(method, params, cancellation);
            return call.reply;
          } catch (error) {
            wireErrors.push({ method, message: String(error) });
            throw error;
          }
        } };
        let handler: any;
        const api: any = { ...vscode, window: { activeTextEditor: undefined },
          workspace: { workspaceFolders: [folder], fs: vscode.workspace.fs, textDocuments: [], getWorkspaceFolder: () => folder },
          chat: { createChatParticipant(_id: string, callback: any) { handler = callback; return {}; } },
        };
        conversation = new ConversationClient(transport, api);
        const store = new PreviewStore(api);
        registerConversationParticipant(api, conversation, languageClient.initializeResult, store);
        const history: any[] = [];
        const stream = { markdown(_value: string) {}, anchor() {}, button() {} };
        const invoke = async (command: string, prompt = '') => {
          const result = await handler({ command, prompt }, { history }, stream, token.token);
          history.push({ result });
          return result;
        };
        const failed = await invoke('compile', 'rust');
        assert.strictEqual(failed.metadata?.modelable?.kind, 'error', JSON.stringify({ failed, initializeResult: languageClient.initializeResult, requests: calls.map(call => call.method) }));
        const sessionId = failed.metadata.modelable.sessionId;
        assert.strictEqual(typeof sessionId, 'string');
        assert.strictEqual(failed.metadata.modelable.changeSetId, null);
        assert.strictEqual(store.hasSession(sessionId), false);
        assert.deepStrictEqual(await fs.readFile(source), sourceBytes);
        assert.deepStrictEqual(await fs.readdir(stages), []);
        await assert.rejects(fs.stat(path.join(workspace, '.modelable', 'registry.db')), { code: 'ENOENT' });
        if (fault === 'malformed-ledger') {
          assert.deepStrictEqual(await fs.readFile(ledger), malformed);
          await fs.writeFile(ledger, '{}');
        }
        const preview = await invoke('compile', 'rust');
        assert.strictEqual(preview.metadata.modelable.kind, 'preview');
        assert.strictEqual(preview.metadata.modelable.sessionId, sessionId);
        const turns = calls.filter(call => call.method === 'modelable/conversation/turn');
        assert.strictEqual(turns[0].params.createSession, true);
        assert.strictEqual(turns[1].params.createSession, false);
        assert.strictEqual(turns[1].params.sessionId, sessionId);
        const previewReply = turns[1].reply;
        const pendingId = preview.metadata.modelable.changeSetId;
        const snapshots = new Map(store.contents);
        assert.ok(snapshots.size > 0);
        const pendingStages = await fs.readdir(stages);
        assert.strictEqual(pendingStages.length, 1);
        if (fault === 'malformed-ledger') await fs.writeFile(ledger, malformed);
        const replacement = await invoke('compile', 'go');
        assert.strictEqual(replacement.metadata.modelable.kind, 'error');
        assert.strictEqual(replacement.metadata.modelable.sessionId, sessionId);
        assert.strictEqual(replacement.metadata.modelable.changeSetId, pendingId);
        assert.strictEqual(replacement.metadata.modelable.operationKind, 'compile');
        assert.deepStrictEqual(store.contents, snapshots);
        assert.deepStrictEqual(await fs.readdir(stages), pendingStages);
        await fs.writeFile(ledger, '{}');
        const applied = await invoke('apply');
        assert.strictEqual(applied.metadata?.modelable?.kind, 'applied', JSON.stringify({ applied, applyCalls: calls.filter(call => call.method === 'modelable/conversation/apply') }));
        assert.strictEqual(store.hasSession(sessionId), false);
        assert.strictEqual(store.contents.size, 0);
        assert.deepStrictEqual(await fs.readdir(stages), []);
        for (const file of previewReply.compilationFiles) {
          assert.strictEqual(createHash('sha256').update(await fs.readFile(vscode.Uri.parse(file.uri).fsPath)).digest('hex'), file.afterHash);
        }
        const fresh = await invoke('compile', 'go');
        assert.strictEqual(fresh.metadata?.modelable?.kind, 'preview', JSON.stringify({ fresh, wireErrors }));
        assert.notStrictEqual(fresh.metadata.modelable.changeSetId, pendingId);
        assert.ok(store.hasSession(sessionId));
        const reset = await invoke('reset');
        assert.strictEqual(reset.metadata.modelable.kind, 'reset');
        assert.strictEqual(store.hasSession(sessionId), false);
        assert.strictEqual(store.contents.size, 0);
        assert.deepStrictEqual(await fs.readdir(stages), []);
        await assert.rejects(languageClient.sendRequest('modelable/conversation/turn', {
          protocolVersion: 2, sessionId, createSession: false, workspaceUri: folder.uri.toString(), message: '/compile rust', dirtyDocumentUris: [],
        }), /unknown or expired/);
      } finally {
        token.dispose();
        try { await conversation?.closeAll(); } finally {
          await languageClient.stop();
          await serverExit;
          output.dispose();
          assert.ok(path.resolve(temporary).startsWith(path.resolve(os.tmpdir()) + path.sep + 'modelable-preview-recovery-'));
          await fs.rm(temporary, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
        }
      }
    });
  }
});
