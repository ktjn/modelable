const { PROTOCOL_VERSION } = require('./conversationClient');

const PARTICIPANT_ID = 'modelable-vscode.modelable';

function registerConversationParticipant(
  vscodeApi,
  conversationClient,
  initializeResult,
) {
  const supported = (
    initializeResult?.capabilities?.experimental
      ?.modelableConversation?.protocolVersion === PROTOCOL_VERSION
  );

  return vscodeApi.chat.createChatParticipant(
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
        const reply = await conversationClient.turn(
          request,
          context,
          token,
        );
        response.markdown(reply.text);
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
  registerConversationParticipant,
  sanitizedErrorMessage,
};
