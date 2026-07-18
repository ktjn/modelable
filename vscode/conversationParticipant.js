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
              'Upgrade the Modelable language server to a version that supports conversation protocol 1.',
          },
        };
      }

      try {
        const metadata = recoverSessionMetadata(context.history ?? []);
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
          label: 'Apply change set',
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
  if (
    reply.kind === 'preview' &&
    reply.sessionId &&
    reply.changeSetId &&
    (reply.previewFiles?.length ?? 0) > 0
  ) {
    previewStore?.put(
      reply.sessionId,
      reply.changeSetId,
      reply.previewFiles,
    );
    stream.button({
      command: 'modelable.conversation.viewDiff',
      title: 'View Diff',
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
      },
    },
  };
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
