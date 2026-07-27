import { lazy, useEffect, useRef, useState } from 'react';

import { providerStatusLabel, type ProviderState } from './provider-state';
import type {
  AssistantGenerateChatMessage,
  AssistantExplainChatMessage,
  ChatMessage,
} from './chat-types';
import { isAssistantGenerateMessage, isAssistantExplainMessage } from './chat-types';
import type { BrowserDiagnostic } from '../protocol';

const DiffViewer = lazy(() =>
  import('./DiffViewer').then((m) => ({ default: m.DiffViewer })),
);

export interface ChatPanelProps {
  messages: ChatMessage[];
  activeFileContent: string;
  aiState: ProviderState;
  actionsDisabled: boolean;
  onSend(text: string): void;
  onExplain(): void;
  onSuggestProjection(): void;
  onAccept(source: string): void;
  onDiscard(messageId: string): void;
  onDownloadModel(): void;
  onUseHeuristic(): void;
}

export function ChatPanel({
  messages,
  activeFileContent,
  aiState,
  actionsDisabled,
  onSend,
  onExplain,
  onSuggestProjection,
  onAccept,
  onDiscard,
  onDownloadModel,
  onUseHeuristic,
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState('');

  useEffect(() => {
    const element = scrollRef.current;
    if (element === null) {
      return;
    }
    element.scrollTop = element.scrollHeight;
  }, [messages]);

  const handleSubmit = (): void => {
    const text = draft.trim();
    if (text === '') return;
    setDraft('');
    onSend(text);
  };

  const composerDisabled = actionsDisabled || aiState.status === 'downloading';
  const providerReady = aiState.status === 'ready';
  const providerLabel = providerStatusLabel(aiState);

  return (
    <section className="chat-panel" aria-label="Assistant">
      <div className="chat-panel__header">
        <span className="chat-panel__title">Assistant</span>
        <span
          className={`chat-panel__status chat-panel__status--${aiState.status}`}
          title={providerLabel}
        >
          {providerLabel}
        </span>
      </div>

      <div className="chat-panel__messages" ref={scrollRef}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            <p>Describe a change or ask a question about your models.</p>
            {providerReady ? (
              <div className="chat-quick-actions" role="group" aria-label="Quick actions">
                <button
                  type="button"
                  className="chip"
                  disabled={actionsDisabled}
                  onClick={onExplain}
                >
                  Explain workspace
                </button>
                <button
                  type="button"
                  className="chip"
                  disabled={actionsDisabled}
                  onClick={onSuggestProjection}
                >
                  Suggest projection
                </button>
              </div>
            ) : null}
          </div>
        ) : (
          messages.map((message) => (
            <ChatMessageItem
              key={message.id}
              message={message}
              activeFileContent={activeFileContent}
              onAccept={onAccept}
              onDiscard={onDiscard}
            />
          ))
        )}
      </div>

      <div className="chat-panel__composer">
        {!providerReady && aiState.status !== 'downloading' ? (
          <div className="chat-onboarding">
            <p>Enable the assistant to generate and explain models.</p>
            <div className="chat-onboarding__actions">
              {aiState.status === 'idle' ? (
                <button type="button" onClick={onDownloadModel}>
                  Download AI model
                </button>
              ) : null}
              {aiState.status === 'unsupported' || aiState.status === 'error' ? (
                <button type="button" onClick={onUseHeuristic}>
                  Use heuristic AI
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <>
            <textarea
              className="chat-composer__input"
              rows={3}
              placeholder="e.g. Add a creditScore field to Customer"
              value={draft}
              disabled={composerDisabled}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
            />
            <div className="chat-composer__actions">
              <span className="chat-composer__hint">Enter to send · Shift+Enter for a new line</span>
              <button
                type="button"
                className="chat-composer__send"
                disabled={composerDisabled || draft.trim() === ''}
                onClick={handleSubmit}
              >
                Send
              </button>
            </div>
            {aiState.status === 'downloading' ? (
              <div className="ai-progress">
                <div
                  className="ai-progress__bar"
                  role="progressbar"
                  aria-valuenow={Math.round(aiState.progress * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  style={{ width: `${(aiState.progress * 100).toFixed(1)}%` }}
                />
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}

interface ChatMessageItemProps {
  message: ChatMessage;
  activeFileContent: string;
  onAccept(source: string): void;
  onDiscard(messageId: string): void;
}

function ChatMessageItem({
  message,
  activeFileContent,
  onAccept,
  onDiscard,
}: ChatMessageItemProps) {
  if (message.role === 'user') {
    return (
      <div className="chat-message chat-message--user">
        <p className="chat-message__text">{message.text}</p>
      </div>
    );
  }

  if (isAssistantExplainMessage(message)) {
    return (
      <AssistantExplainMessageItem
        message={message}
        onDiscard={onDiscard}
      />
    );
  }

  if (isAssistantGenerateMessage(message)) {
    return (
      <AssistantGenerateMessageItem
        message={message}
        activeFileContent={activeFileContent}
        onAccept={onAccept}
        onDiscard={onDiscard}
      />
    );
  }

  return null;
}

function AssistantExplainMessageItem({
  message,
  onDiscard,
}: {
  message: AssistantExplainChatMessage;
  onDiscard(messageId: string): void;
}) {
  return (
    <div className="chat-message chat-message--assistant">
      <h2 className="chat-message__title">AI explanation</h2>
      <p className="chat-message__provider">
        {message.providerInfo.provider} / {message.providerInfo.model}
      </p>
      {message.pending ? (
        <p className="chat-message__pending">Thinking…</p>
      ) : message.outcome === 'discarded' ? (
        <p className="chat-message__outcome">Discarded</p>
      ) : message.explanation === undefined ? (
        <p className="chat-message__pending">No explanation received</p>
      ) : (
        <div className="chat-message__explanation">{message.explanation}</div>
      )}
      <DiagnosticsList diagnostics={message.diagnostics} />
      {!message.pending && message.outcome === undefined ? (
        <div className="chat-message__actions">
          <button type="button" onClick={() => onDiscard(message.id)}>
            Close
          </button>
        </div>
      ) : null}
    </div>
  );
}

function AssistantGenerateMessageItem({
  message,
  activeFileContent,
  onAccept,
  onDiscard,
}: {
  message: AssistantGenerateChatMessage;
  activeFileContent: string;
  onAccept(source: string): void;
  onDiscard(messageId: string): void;
}) {
  const [showDiff, setShowDiff] = useState(false);

  return (
    <div className="chat-message chat-message--assistant">
      <h2 className="chat-message__title">AI generated source</h2>
      <p className="chat-message__provider">
        {message.providerInfo.provider} / {message.providerInfo.model}
      </p>
      {message.pending ? (
        <p className="chat-message__pending">Generating…</p>
      ) : message.outcome === 'accepted' ? (
        <p className="chat-message__outcome">Accepted</p>
      ) : message.outcome === 'discarded' ? (
        <p className="chat-message__outcome">Discarded</p>
      ) : (
        <>
          {message.source === undefined ? (
            <p className="chat-message__pending">No source generated</p>
          ) : showDiff ? (
            <div className="chat-message__diff">
              <DiffViewer original={activeFileContent} modified={message.source} />
            </div>
          ) : (
            <SourcePreview source={message.source} />
          )}
          <DiagnosticsList diagnostics={message.diagnostics} />
          <div className="chat-message__actions">
            {message.source !== undefined && activeFileContent !== message.source ? (
              <button
                type="button"
                className="chip"
                onClick={() => setShowDiff((value) => !value)}
              >
                {showDiff ? 'Hide diff' : 'Compare with current file'}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => onAccept(message.source ?? '')}
              disabled={message.source === undefined}
            >
              Accept
            </button>
            <button type="button" onClick={() => onDiscard(message.id)}>
              Discard
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function SourcePreview({ source }: { source: string }) {
  const [html, setHtml] = useState('');

  useEffect(() => {
    void import('monaco-editor/esm/vs/editor/editor.api.js').then((monaco) => {
      void monaco.editor.colorize(source, 'modelable', {}).then(setHtml);
    });
  }, [source]);

  return (
    <pre
      className="chat-message__source monaco-editor-background"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function DiagnosticsList({ diagnostics }: { diagnostics: BrowserDiagnostic[] }) {
  if (diagnostics.length === 0) return null;

  return (
    <ul className="chat-message__diagnostics">
      {diagnostics.map((diagnostic, index) => (
        <li key={`${diagnostic.code}-${index}`}>
          <strong>{diagnostic.code}</strong>{' '}
          {diagnostic.message}
        </li>
      ))}
    </ul>
  );
}
