const {
  PROTOCOL_VERSION,
  recoverSessionMetadata,
} = require('./conversationClient');

const PARTICIPANT_ID = 'modelable-vscode.modelable';

function registerConversationParticipant(
  vscodeApi,
  conversationClient,
  initializeResult,
  previewStore,
) {
  const supported = (
    initializeResult?.capabilities?.experimental
      ?.modelableConversation?.protocolVersion === PROTOCOL_VERSION
  );

  const participant = vscodeApi.chat.createChatParticipant(
    PARTICIPANT_ID,
    async (request, context, response, token) => {
      if (!supported) {
        return {
          errorDetails: {
            message:
              'Upgrade the Modelable language server to a version that supports conversation protocol 2.',
          },
        };
      }

      const metadata = recoverSessionMetadata(context.history ?? []);
      try {
        if (request.command === 'reset') {
          if (metadata?.sessionId) {
            await conversationClient.close(metadata.sessionId);
            previewStore?.deleteSession(metadata.sessionId);
          }
          response.markdown('Reset the Modelable conversation session.');
          return {
            metadata: {
              modelable: {
                protocolVersion: PROTOCOL_VERSION,
                workspaceUri: metadata?.workspaceUri,
                kind: 'reset',
              },
            },
          };
        }

        let reply;
        if (request.command === 'apply' || request.command === 'discard') {
          requirePendingMetadata(metadata);
          if (request.command === 'apply') {
            const dirtyDocumentUris = conversationClient.dirtyDocumentUris(
              metadata.workspaceUri,
            );
            reply = await conversationClient.apply(
              metadata,
              dirtyDocumentUris,
              token,
            );
          } else {
            reply = await conversationClient.discard(metadata, token);
          }
        } else {
          reply = await conversationClient.turn(
            request,
            context,
            token,
          );
        }
        renderReply(reply, response, vscodeApi, previewStore);
        if (
          (reply.kind === 'applied' || reply.kind === 'discarded') &&
          reply.sessionId &&
          reply.changeSetId
        ) {
          previewStore?.deleteChangeSet(
            reply.sessionId,
            reply.changeSetId,
          );
        }
        return chatResult(reply);
      } catch (error) {
        const cancelled = (
          request.command !== 'apply' &&
          (
            token?.isCancellationRequested ||
            (
              vscodeApi.CancellationError &&
              error instanceof vscodeApi.CancellationError
            )
          )
        );
        if (cancelled) {
          const sessionId = error?.modelableSessionId ?? metadata?.sessionId;
          if (sessionId) {
            conversationClient.forgetSession(sessionId);
            previewStore?.deleteSession(sessionId);
          }
          return {};
        }
        if (
          metadata?.sessionId &&
          /unknown or expired|session.*expired/i.test(
            error instanceof Error ? error.message : '',
          )
        ) {
          conversationClient.forgetSession(metadata.sessionId);
          previewStore?.deleteSession(metadata.sessionId);
          return {
            errorDetails: {
              message:
                'The Modelable conversation session expired or the language server restarted. Repeat the request to start a fresh session.',
            },
          };
        }
        return {
          errorDetails: {
            message: sanitizedErrorMessage(error),
          },
        };
      }
    },
  );
  participant.followupProvider = {
    provideFollowups(result) {
      if (result?.metadata?.modelable?.kind !== 'preview') {
        return [];
      }
      return [
        {
          prompt: '',
          label: result.metadata.modelable.operationKind === 'compile'
            ? 'Apply compilation'
            : 'Apply change set',
          participant: PARTICIPANT_ID,
          command: 'apply',
        },
        {
          prompt: '',
          label: 'Discard',
          participant: PARTICIPANT_ID,
          command: 'discard',
        },
      ];
    },
  };
  return participant;
}

function requirePendingMetadata(metadata) {
  if (
    !metadata?.sessionId ||
    !metadata.workspaceUri ||
    !metadata.changeSetId
  ) {
    throw new Error(
      'There is no current pending change set. Request a fresh preview before applying or discarding.',
    );
  }
}

function renderReply(reply, stream, vscodeApi, previewStore) {
  stream.markdown(reply.text);
  for (const definition of [
    ...(reply.changedDefinitions ?? []),
    ...(reply.affectedDefinitions ?? []),
  ]) {
    if (definition.location?.uri) {
      stream.anchor(
        vscodeApi.Uri.parse(definition.location.uri),
        definition.ref,
      );
    }
  }
  const compilationFiles = reply.compilationFiles ?? [];
  const textFiles = compilationFiles
    .filter(file => (
      typeof file.beforeText === 'string' &&
      typeof file.afterText === 'string'
    ))
    .map(file => ({
      uri: file.uri,
      existedBefore: file.status !== 'created',
      beforeText: file.beforeText,
      afterText: file.afterText,
    }));
  const binaryFiles = compilationFiles.filter(file => (
    typeof file.beforeText !== 'string' ||
    typeof file.afterText !== 'string'
  ));
  for (const file of binaryFiles) {
    stream.markdown(
      `\n\n- Binary ${inlineCode(file.category)} ` +
      `${inlineCode(file.status)} ${inlineCode(fileName(file.uri))}: ` +
      `${safeInteger(file.afterSize)} bytes, SHA-256 ` +
      `${inlineCode(file.afterHash ?? 'unavailable')}`,
    );
  }
  for (const item of reply.registryIdChanges ?? []) {
    stream.markdown(
      `\n\n- Registry ID ${inlineCode(item.ref)}: ` +
      `${safeInteger(item.registryId)}`,
    );
  }
  if (reply.auditUri) {
    stream.anchor(
      vscodeApi.Uri.parse(reply.auditUri),
      'View compilation audit',
    );
  }
  if (
    reply.kind === 'preview' &&
    reply.sessionId &&
    reply.changeSetId &&
    (
      (reply.previewFiles?.length ?? 0) > 0 ||
      textFiles.length > 0
    )
  ) {
    previewStore?.put(
      reply.sessionId,
      reply.changeSetId,
      reply.operationKind === 'compile'
        ? textFiles
        : reply.previewFiles,
    );
    stream.button({
      command: 'modelable.conversation.viewDiff',
      title: reply.operationKind === 'compile'
        ? 'View generated diffs'
        : 'View Diff',
      arguments: [{
        sessionId: reply.sessionId,
        changeSetId: reply.changeSetId,
      }],
    });
  }
}

function chatResult(reply) {
  return {
    metadata: {
      modelable: {
        protocolVersion: PROTOCOL_VERSION,
        sessionId: reply.sessionId,
        workspaceUri: reply.workspaceUri,
        changeSetId: reply.changeSetId,
        kind: reply.kind,
        ...(reply.operationKind
          ? { operationKind: reply.operationKind }
          : {}),
      },
    },
  };
}

function fileName(uri) {
  try {
    const pathname = decodeURIComponent(new URL(uri).pathname);
    return safeText(pathname.split('/').pop() || uri);
  } catch {
    return safeText(uri);
  }
}

function safeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0 ? String(value) : 'unknown';
}

function safeText(value) {
  return String(value ?? '')
    .replace(/\x1B(?:[@-_][0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))/g, '')
    .replace(/[\u0000-\u001F\u007F-\u009F\u061C\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]/g, '');
}

function inlineCode(value) {
  const safe = safeText(value);
  const longestRun = Math.max(
    0,
    ...([...safe.matchAll(/`+/g)].map(match => match[0].length)),
  );
  const fence = '`'.repeat(longestRun + 1);
  return `${fence} ${safe} ${fence}`;
}

function sanitizedErrorMessage(error) {
  const message = error instanceof Error ? error.message : '';
  if (
    /save these files/i.test(message) ||
    /different workspace/i.test(message) ||
    /unknown or expired/i.test(message) ||
    /current pending change set/i.test(message) ||
    /open a Modelable file/i.test(message) ||
    /multiple Modelable workspaces/i.test(message) ||
    /reset or start a new chat/i.test(message)
  ) {
    return message;
  }
  return (
    'Modelable could not complete the request. ' +
    'Check the Modelable language server output and try again.'
  );
}

module.exports = {
  PARTICIPANT_ID,
  chatResult,
  requirePendingMetadata,
  renderReply,
  registerConversationParticipant,
  sanitizedErrorMessage,
};
