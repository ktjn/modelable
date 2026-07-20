const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const vscode = require('vscode');

const PROTOCOL_VERSION = 2;
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
  const dirtyDocumentUris = collectDirtyDocumentUris(
    vscodeApi,
    selectedFolder.uri.toString(),
  );

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
  constructor(
    languageClient,
    vscodeApi = vscode,
    randomUUID = crypto.randomUUID,
    outputChannel,
  ) {
    this.languageClient = languageClient;
    this.vscode = vscodeApi;
    this.randomUUID = randomUUID;
    this.outputChannel = outputChannel;
    this.sessionIds = new Set();
    this.invalidatedSessionIds = new Set();
  }

  async turn(request, chatContext, token) {
    const recovered = recoverSessionMetadata(chatContext.history ?? []);
    const metadata = (
      recovered && !this.invalidatedSessionIds.has(recovered.sessionId)
    )
      ? recovered
      : undefined;
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
    const startedAt = Date.now();
    this._log(
      `conversation kind=turn protocol=${PROTOCOL_VERSION} lifecycle=${
        metadata === undefined ? 'create' : 'continue'
      }`,
    );
    try {
      const reply = await this.languageClient.sendRequest(
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
      this._log(
        `conversation kind=turn protocol=${PROTOCOL_VERSION} ` +
        `elapsedMs=${Date.now() - startedAt} reply=${reply.kind}`,
      );
      return reply;
    } catch (error) {
      const cancelled = (
        token?.isCancellationRequested ||
        (
          this.vscode.CancellationError &&
          error instanceof this.vscode.CancellationError
        )
      );
      if (cancelled) {
        error.modelableSessionId = sessionId;
        this.forgetSession(sessionId);
        try {
          await this._closeRequest(sessionId);
        } catch {
          // Cancellation invalidation is local-first; server cleanup is best effort.
        }
        this._log(
          `conversation kind=turn protocol=${PROTOCOL_VERSION} ` +
          `elapsedMs=${Date.now() - startedAt} error=cancelled`,
        );
      } else {
        this._log(
          `conversation kind=turn protocol=${PROTOCOL_VERSION} ` +
          `elapsedMs=${Date.now() - startedAt} error=${errorCode(error)}`,
        );
      }
      throw error;
    }
  }

  apply(metadata, dirtyDocumentUris) {
    return this.languageClient.sendRequest(
      APPLY_METHOD,
      {
        protocolVersion: PROTOCOL_VERSION,
        sessionId: metadata.sessionId,
        changeSetId: metadata.changeSetId,
        dirtyDocumentUris: dirtyDocumentUris.map(uri => uri.toString()),
      },
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

  dirtyDocumentUris(workspaceUri) {
    return collectDirtyDocumentUris(this.vscode, workspaceUri);
  }

  async close(sessionId) {
    this.forgetSession(sessionId);
    await this._closeRequest(sessionId);
  }

  async closeAll() {
    const sessionIds = [...this.sessionIds];
    await Promise.allSettled(sessionIds.map(sessionId => this.close(sessionId)));
  }

  forgetSession(sessionId) {
    this.sessionIds.delete(sessionId);
    this.invalidatedSessionIds.add(sessionId);
  }

  async _closeRequest(sessionId) {
    this._log(
      `conversation lifecycle=close protocol=${PROTOCOL_VERSION}`,
    );
    return this.languageClient.sendRequest(CLOSE_METHOD, {
      protocolVersion: PROTOCOL_VERSION,
      sessionId,
    });
  }

  _log(message) {
    this.outputChannel?.appendLine(message);
  }
}

function collectDirtyDocumentUris(vscodeApi, workspaceUri) {
  return (vscodeApi.workspace.textDocuments ?? [])
    .filter(document => (
      document.isDirty &&
      document.uri?.scheme === 'file' &&
      isFileUriInsideWorkspace(vscodeApi, workspaceUri, document.uri)
    ))
    .map(document => document.uri)
    .sort((left, right) => left.toString().localeCompare(right.toString()));
}

function isFileUriInsideWorkspace(vscodeApi, workspaceUri, documentUri) {
  try {
    const rootUri = vscodeApi.Uri.parse(workspaceUri);
    if (rootUri.scheme !== 'file' || documentUri?.scheme !== 'file') {
      return false;
    }
    const rootPath = canonicalPath(rootUri.fsPath);
    const documentPath = canonicalPath(documentUri.fsPath);
    const relative = path.relative(rootPath, documentPath);
    return (
      relative === '' ||
      (
        relative !== '..' &&
        !relative.startsWith(`..${path.sep}`) &&
        !path.isAbsolute(relative)
      )
    );
  } catch {
    return false;
  }
}

function canonicalPath(filePath) {
  const resolved = path.resolve(filePath);
  try {
    return fs.realpathSync.native(resolved);
  } catch {
    return resolved;
  }
}

function errorCode(error) {
  const message = error instanceof Error ? error.message : '';
  if (/expired/i.test(message)) {
    return 'session_expired';
  }
  if (/provider/i.test(message)) {
    return 'provider';
  }
  if (/protocol/i.test(message)) {
    return 'protocol';
  }
  return 'request_failed';
}

module.exports = {
  APPLY_METHOD,
  CLOSE_METHOD,
  ConversationClient,
  ConversationContextError,
  DISCARD_METHOD,
  PROTOCOL_VERSION,
  TURN_METHOD,
  collectDirtyDocumentUris,
  errorCode,
  isFileUriInsideWorkspace,
  recoverSessionMetadata,
  resolveConversationContext,
};
