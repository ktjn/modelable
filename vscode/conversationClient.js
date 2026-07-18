const crypto = require('crypto');
const vscode = require('vscode');

const PROTOCOL_VERSION = 1;
const TURN_METHOD = 'modelable/conversation/turn';
const APPLY_METHOD = 'modelable/conversation/apply';
const DISCARD_METHOD = 'modelable/conversation/discard';
const CLOSE_METHOD = 'modelable/conversation/close';

class ConversationContextError extends Error {}

function recoverSessionMetadata(history) {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const modelable = history[index]?.result?.metadata?.modelable;
    if (
      modelable?.protocolVersion === PROTOCOL_VERSION &&
      typeof modelable.sessionId === 'string' &&
      typeof modelable.workspaceUri === 'string'
    ) {
      return modelable;
    }
  }
  return undefined;
}

async function resolveConversationContext(vscodeApi = vscode) {
  const editor = vscodeApi.window.activeTextEditor;
  const activeDocument = editor?.document;
  let selectedFolder;

  if (
    activeDocument?.uri?.scheme === 'file' &&
    activeDocument.languageId === 'mdl'
  ) {
    selectedFolder = vscodeApi.workspace.getWorkspaceFolder(activeDocument.uri);
  }

  if (!selectedFolder) {
    const candidates = [];
    for (const folder of vscodeApi.workspace.workspaceFolders ?? []) {
      try {
        await vscodeApi.workspace.fs.stat(
          vscodeApi.Uri.joinPath(folder.uri, 'workspace.mdl'),
        );
        candidates.push(folder);
      } catch {
        // A workspace folder without a Modelable manifest is not a candidate.
      }
    }
    if (candidates.length > 1) {
      throw new ConversationContextError(
        'Multiple Modelable workspaces are open. Open a .mdl file in the workspace you want to manage.',
      );
    }
    selectedFolder = candidates[0];
  }

  if (!selectedFolder) {
    throw new ConversationContextError(
      'Open a Modelable file or a workspace folder containing workspace.mdl before using @modelable.',
    );
  }

  const activeDocumentUri = (
    activeDocument?.languageId === 'mdl' &&
    vscodeApi.workspace.getWorkspaceFolder(activeDocument.uri)?.uri.toString() ===
      selectedFolder.uri.toString()
  )
    ? activeDocument.uri
    : undefined;
  const dirtyDocumentUris = (vscodeApi.workspace.textDocuments ?? [])
    .filter(document => (
      document.isDirty &&
      document.languageId === 'mdl' &&
      vscodeApi.workspace.getWorkspaceFolder(document.uri)?.uri.toString() ===
        selectedFolder.uri.toString()
    ))
    .map(document => document.uri)
    .sort((left, right) => left.toString().localeCompare(right.toString()));

  return {
    workspaceUri: selectedFolder.uri,
    activeDocumentUri,
    position: activeDocumentUri
      ? {
          line: editor.selection.active.line,
          character: editor.selection.active.character,
        }
      : undefined,
    dirtyDocumentUris,
  };
}

class ConversationClient {
  constructor(languageClient, vscodeApi = vscode, randomUUID = crypto.randomUUID) {
    this.languageClient = languageClient;
    this.vscode = vscodeApi;
    this.randomUUID = randomUUID;
    this.sessionIds = new Set();
  }

  async turn(request, chatContext, token) {
    const metadata = recoverSessionMetadata(chatContext.history ?? []);
    const context = await resolveConversationContext(this.vscode);
    if (
      metadata !== undefined &&
      metadata.workspaceUri !== context.workspaceUri.toString()
    ) {
      throw new ConversationContextError(
        'This conversation belongs to a different workspace. Use /reset or start a new chat before continuing.',
      );
    }
    const sessionId = metadata?.sessionId ?? this.randomUUID();
    const message = request.command === 'help'
      ? 'describe the current workspace and supported management tasks'
      : request.prompt;
    this.sessionIds.add(sessionId);

    return this.languageClient.sendRequest(
      TURN_METHOD,
      {
        protocolVersion: PROTOCOL_VERSION,
        sessionId,
        createSession: metadata === undefined,
        workspaceUri: context.workspaceUri.toString(),
        message,
        activeDocumentUri: context.activeDocumentUri?.toString(),
        position: context.position,
        dirtyDocumentUris: context.dirtyDocumentUris.map(uri => uri.toString()),
      },
      token,
    );
  }

  apply(metadata, dirtyDocumentUris, token) {
    return this.languageClient.sendRequest(
      APPLY_METHOD,
      {
        protocolVersion: PROTOCOL_VERSION,
        sessionId: metadata.sessionId,
        changeSetId: metadata.changeSetId,
        dirtyDocumentUris: dirtyDocumentUris.map(uri => uri.toString()),
      },
      token,
    );
  }

  discard(metadata, token) {
    return this.languageClient.sendRequest(
      DISCARD_METHOD,
      {
        protocolVersion: PROTOCOL_VERSION,
        sessionId: metadata.sessionId,
        changeSetId: metadata.changeSetId,
        dirtyDocumentUris: [],
      },
      token,
    );
  }

  async close(sessionId) {
    try {
      await this.languageClient.sendRequest(CLOSE_METHOD, {
        protocolVersion: PROTOCOL_VERSION,
        sessionId,
      });
    } finally {
      this.sessionIds.delete(sessionId);
    }
  }

  async closeAll() {
    const sessionIds = [...this.sessionIds];
    await Promise.allSettled(sessionIds.map(sessionId => this.close(sessionId)));
  }
}

module.exports = {
  APPLY_METHOD,
  CLOSE_METHOD,
  ConversationClient,
  ConversationContextError,
  DISCARD_METHOD,
  PROTOCOL_VERSION,
  TURN_METHOD,
  recoverSessionMetadata,
  resolveConversationContext,
};
