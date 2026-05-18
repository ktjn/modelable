const fs = require('fs');
const path = require('path');

const vscode = require('vscode');
const {
  LanguageClient,
  RevealOutputChannelOn,
} = require('vscode-languageclient/node');

let client;

function resolveServerCommand(context) {
  const repoRoot = path.resolve(context.extensionPath, '..');
  const cliRoot = path.join(repoRoot, 'cli');
  const python = process.platform === 'win32'
    ? path.join(cliRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(cliRoot, '.venv', 'bin', 'python');

  return { cliRoot, python };
}

async function activate(context) {
  const outputChannel = vscode.window.createOutputChannel('Modelable LSP');
  const { cliRoot, python } = resolveServerCommand(context);

  if (!fs.existsSync(python)) {
    vscode.window.showErrorMessage(
      `Modelable LSP could not find the repo-local Python interpreter at ${python}. Run uv sync --extra dev in cli/ first.`
    );
    return;
  }

  const serverOptions = {
    command: python,
    args: ['-m', 'modelable.lsp'],
    options: {
      cwd: cliRoot,
    },
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

  client = new LanguageClient(
    'modelable',
    'Modelable Language Server',
    serverOptions,
    clientOptions,
  );

  await client.start();
  context.subscriptions.push(client, outputChannel);
}

async function deactivate() {
  if (client) {
    await client.stop();
    client = undefined;
  }
}

module.exports = {
  activate,
  deactivate,
};
