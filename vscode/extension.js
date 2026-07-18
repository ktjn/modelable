const fs = require('fs');
const path = require('path');

const vscode = require('vscode');
const {
  LanguageClient,
  RevealOutputChannelOn,
} = require('vscode-languageclient/node');
const { ConversationClient } = require('./conversationClient');
const {
  registerConversationParticipant,
} = require('./conversationParticipant');
const { PreviewStore } = require('./conversationPreview');

let client;
let conversationClient;

/**
 * Resolution order:
 *   1. `modelable.serverCommand` setting — explicit `[command, ...args]` override.
 *   2. `modelable.pythonPath` setting — interpreter launched as `<pythonPath> -m modelable.lsp`.
 *   3. The repo-local `cli/.venv` next to this extension (development checkout of modelable itself).
 *   4. `modelable lsp` resolved from PATH (the CLI installed into the host project's environment).
 */
function resolveServerOptions(context) {
  const config = vscode.workspace.getConfiguration('modelable');

  const serverCommand = config.get('serverCommand');
  if (Array.isArray(serverCommand) && serverCommand.length > 0) {
    const [command, ...args] = serverCommand;
    return { command, args, source: '"modelable.serverCommand" setting' };
  }

  const pythonPath = config.get('pythonPath');
  if (typeof pythonPath === 'string' && pythonPath.trim().length > 0) {
    return { command: pythonPath, args: ['-m', 'modelable.lsp'], source: '"modelable.pythonPath" setting' };
  }

  const repoRoot = path.resolve(context.extensionPath, '..');
  const cliRoot = path.join(repoRoot, 'cli');
  const repoLocalPython = process.platform === 'win32'
    ? path.join(cliRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(cliRoot, '.venv', 'bin', 'python');
  if (fs.existsSync(repoLocalPython)) {
    return {
      command: repoLocalPython,
      args: ['-m', 'modelable.lsp'],
      cwd: cliRoot,
      source: 'repo-local cli/.venv (development checkout)',
    };
  }

  return { command: 'modelable', args: ['lsp'], source: '"modelable" resolved from PATH' };
}

async function activate(context) {
  const outputChannel = vscode.window.createOutputChannel('Modelable LSP', { log: true });
  const { command, args, cwd, source } = resolveServerOptions(context);
  outputChannel.appendLine(`Starting Modelable language server via ${source}: ${command} ${args.join(' ')}`);

  const serverOptions = {
    command,
    args,
    options: cwd ? { cwd } : {},
  };

  const clientOptions = {
    documentSelector: [
      { scheme: 'file', language: 'mdl' },
    ],
    synchronize: {
      fileEvents: vscode.workspace.createFileSystemWatcher('**/*.mdl'),
    },
    outputChannel,
    revealOutputChannelOn: RevealOutputChannelOn.Error,
  };

  const nextClient = new LanguageClient(
    'modelable',
    'Modelable Language Server',
    serverOptions,
    clientOptions,
  );

  try {
    await nextClient.start();
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    outputChannel.dispose();
    vscode.window.showErrorMessage(
      `Modelable LSP failed to start using "${command} ${args.join(' ')}" (${source}). ` +
      'Install the modelable CLI in this project (see docs/getting-started.md) so "modelable" ' +
      'is on PATH, or set "modelable.pythonPath"/"modelable.serverCommand" to point at an ' +
      `interpreter or command that has it. Details: ${reason}`
    );
    throw error;
  }

  client = nextClient;
  conversationClient = new ConversationClient(nextClient);
  const previewStore = new PreviewStore(vscode);
  const participant = registerConversationParticipant(
    vscode,
    conversationClient,
    nextClient.initializeResult,
    previewStore,
  );
  const previewProvider = vscode.workspace.registerTextDocumentContentProvider(
    'modelable-preview',
    previewStore,
  );
  const viewDiffCommand = vscode.commands.registerCommand(
    'modelable.conversation.viewDiff',
    args => previewStore.showDiff(args.sessionId, args.changeSetId),
  );
  const conversationCleanup = {
    dispose() {
      void conversationClient?.closeAll();
    },
  };
  context.subscriptions.push(
    client,
    outputChannel,
    participant,
    previewProvider,
    viewDiffCommand,
    conversationCleanup,
  );
}

async function deactivate() {
  if (conversationClient) {
    await conversationClient.closeAll();
    conversationClient = undefined;
  }
  if (client) {
    await client.stop();
    client = undefined;
  }
}

module.exports = {
  activate,
  deactivate,
};
