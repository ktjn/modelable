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
    return server(command, args, { source: '"modelable.serverCommand" setting' });
  }

  const pythonPath = config.get('pythonPath');
  if (typeof pythonPath === 'string' && pythonPath.trim().length > 0) {
    return server(
      pythonPath,
      ['-m', 'modelable.lsp'],
      { source: '"modelable.pythonPath" setting' },
    );
  }

  const repoRoot = path.resolve(context.extensionPath, '..');
  const cliRoot = path.join(repoRoot, 'cli');
  const repoLocalPython = process.platform === 'win32'
    ? path.join(cliRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(cliRoot, '.venv', 'bin', 'python');
  if (fs.existsSync(repoLocalPython)) {
    return server(
      repoLocalPython,
      ['-m', 'modelable.lsp'],
      { cwd: cliRoot, source: 'repo-local cli/.venv (development checkout)' },
    );
  }

  return server('modelable', ['lsp'], {
    source: '"modelable" resolved from PATH',
  });
}

/**
 * Build a server launch descriptor, attaching any `modelable.llm.*` settings
 * to the child process environment so the language server's own LLM config
 * resolution picks them up (as MODELABLE_LLM_PROVIDER / _MODEL / _BASE_URL).
 */
function server(command, args, { cwd, source }) {
  const options = cwd ? { cwd } : {};
  const env = llmEnvironment();
  if (Object.keys(env).length > 0) {
    options.env = { ...process.env, ...env };
  }
  return { command, args, cwd, env, source, options };
}

const LLM_ENV_VARIABLES = {
  'llm.provider': 'MODELABLE_LLM_PROVIDER',
  'llm.model': 'MODELABLE_LLM_MODEL',
  'llm.baseUrl': 'MODELABLE_LLM_BASE_URL',
};

/**
 * Read the `modelable.llm.*` settings and return the environment variables to
 * forward to the language server. Empty/unset settings are omitted so the
 * server can fall back to its own resolution (workspace `ai:` block or the
 * ambient process environment).
 */
function llmEnvironment(config = vscode.workspace.getConfiguration('modelable')) {
  const env = {};
  for (const [setting, variable] of Object.entries(LLM_ENV_VARIABLES)) {
    const value = config.get(setting);
    if (typeof value === 'string' && value.trim().length > 0) {
      env[variable] = value.trim();
    }
  }
  return env;
}

async function activate(context) {
  const outputChannel = vscode.window.createOutputChannel('Modelable LSP', { log: true });
  const { command, args, source, options } = resolveServerOptions(context);
  outputChannel.appendLine(`Starting Modelable language server via ${source}: ${command} ${args.join(' ')}`);

  const serverOptions = {
    command,
    args,
    options,
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
  conversationClient = new ConversationClient(
    nextClient,
    vscode,
    undefined,
    outputChannel,
  );
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
  const testConversationCommand = (
    context.extensionMode === vscode.ExtensionMode.Test
  )
    ? vscode.commands.registerCommand(
        'modelable.test.conversationTurn',
        async args => {
          if (args.resetSessionId) {
            await conversationClient.close(args.resetSessionId);
            previewStore.deleteSession(args.resetSessionId);
            return { kind: 'reset' };
          }
          const tokenSource = new vscode.CancellationTokenSource();
          try {
            return await conversationClient.turn(
              { prompt: args.prompt },
              { history: [] },
              tokenSource.token,
            );
          } finally {
            tokenSource.dispose();
          }
        },
      )
    : undefined;
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
    ...(testConversationCommand ? [testConversationCommand] : []),
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
