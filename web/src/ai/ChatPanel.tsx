import { lazy, useCallback, useEffect, useRef, useState } from 'react';

import { providerStatusLabel, type ProviderState } from './provider-state';
import type {
  AssistantGenerateChatMessage,
  AssistantDocsChatMessage,
  AssistantExplainChatMessage,
  ChatMessage,
} from './chat-types';
import {
  isAssistantDocsMessage,
  isAssistantGenerateMessage,
  isAssistantExplainMessage,
} from './chat-types';
import type { BrowserDiagnostic } from '../protocol';
import { type ModelOption } from './webgpu-provider';
import { MarkdownText } from './MarkdownText';

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
  onAccept(source: string, actionId?: string): void;
  onDiscard(messageId: string): void;
  onDownloadModel(): void;
  onUseHeuristic(): void;
  selectedModel: string;
  onModelChange: (model: string) => void;
  models: ModelOption[];
  onReset: () => void;
  onAddModel: (id: string) => void;
  onFetchModels: (url: string) => void;
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
  selectedModel,
  onModelChange,
  models,
  onReset,
  onAddModel,
  onFetchModels,
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState('');
  const [showAddCustom, setShowAddCustom] = useState(false);
  const [customModelId, setCustomModelId] = useState('');

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
        <div className="chat-panel__header-actions">
          {providerReady || aiState.status === 'error' ? (
            <button
              type="button"
              className="chip chip--small"
              onClick={onReset}
              title="Reset AI to change model"
            >
              Change model
            </button>
          ) : null}
          <span
            className={`chat-panel__status chat-panel__status--${aiState.status}`}
            title={providerLabel}
          >
            {providerLabel}
          </span>
        </div>
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
                <>
                  <div className="chat-model-selector">
                    {!showAddCustom ? (
                      <div className="chat-model-selector__row">
                        <select
                          className="chat-model-select"
                          aria-label="AI model"
                          value={selectedModel}
                          onChange={(e) => {
                            if (e.target.value === '__add_custom__') {
                              setShowAddCustom(true);
                            } else {
                              onModelChange(e.target.value);
                            }
                          }}
                        >
                          {models.map((m: ModelOption) => {
                            const tierLabel =
                              m.recommendedTier === 'fast'
                                ? ' (Recommended · Fast)'
                                : m.recommendedTier === 'balanced'
                                  ? ' (Recommended · Balanced)'
                                  : m.recommendedTier === 'quality'
                                    ? ' (Recommended · Quality)'
                                    : '';
                            return (
                              <option key={m.id} value={m.id}>
                                {m.label} — {m.description}
                                {tierLabel}
                              </option>
                            );
                          })}
                          <option value="__add_custom__">+ Add custom model…</option>
                        </select>
                        <button type="button" onClick={onDownloadModel}>
                          Download AI model
                        </button>
                      </div>
                    ) : (
                      <div className="chat-model-selector__row">
                        <input
                          type="text"
                          className="chat-model-input"
                          placeholder="Model ID or URL to models.json"
                          value={customModelId}
                          onChange={(e) => setCustomModelId(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              if (customModelId.trim()) {
                                const val = customModelId.trim();
                                if (val.startsWith('http://') || val.startsWith('https://')) {
                                  onFetchModels(val);
                                } else {
                                  onAddModel(val);
                                }
                                setShowAddCustom(false);
                                setCustomModelId('');
                              }
                            } else if (e.key === 'Escape') {
                              setShowAddCustom(false);
                            }
                          }}
                        />
                        <button
                          type="button"
                          disabled={!customModelId.trim()}
                          onClick={() => {
                            const val = customModelId.trim();
                            if (val.startsWith('http://') || val.startsWith('https://')) {
                              onFetchModels(val);
                            } else {
                              onAddModel(val);
                            }
                            setShowAddCustom(false);
                            setCustomModelId('');
                          }}
                        >
                          Add
                        </button>
                        <button
                          type="button"
                          className="chip"
                          onClick={() => setShowAddCustom(false)}
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                </>
              ) : null}
              {aiState.status === 'unsupported' || aiState.status === 'error' ? (
                <button type="button" onClick={onUseHeuristic}>
                  Use simulator
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <>
            <textarea
              className="chat-composer__input"
              rows={4}
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
  onAccept(source: string, actionId?: string): void;
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

  if (isAssistantDocsMessage(message)) {
    return <AssistantDocsMessageItem message={message} onDiscard={onDiscard} />;
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

function AssistantDocsMessageItem({
  message,
  onDiscard,
}: {
  message: AssistantDocsChatMessage;
  onDiscard(messageId: string): void;
}) {
  return (
    <div className="chat-message chat-message--assistant">
      <h2 className="chat-message__title">Documentation answer</h2>
      <p className="chat-message__provider">
        {message.providerInfo.provider} / {message.providerInfo.model}
      </p>
      {message.pending ? (
        <p className="chat-message__pending">Searching documentation…</p>
      ) : message.answer === undefined ? (
        <p className="chat-message__pending">No documentation answer received</p>
      ) : (
        <>
          <div className="chat-message__explanation">
            <MarkdownText>{message.answer}</MarkdownText>
          </div>
          {message.citations.length > 0 ? (
            <div className="chat-message__citations">
              <h3>Sources</h3>
              <ul>
                {message.citations.map((citation) => (
                  <li key={`${citation.label}-${citation.url}`}>
                    <SafeCitationLink citation={citation} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
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

function SafeCitationLink({
  citation,
}: {
  citation: AssistantDocsChatMessage['citations'][number];
}) {
  const label = `${citation.label} ${citation.externalId}`.trim();
  try {
    const url = new URL(citation.url);
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      return (
        <a href={url.href} target="_blank" rel="noreferrer">
          {label}
        </a>
      );
    }
  } catch {
    // Render untrusted citation URLs as text.
  }
  return <span>{label}</span>;
}

function AssistantExplainMessageItem({
  message,
  onDiscard,
}: {
  message: AssistantExplainChatMessage;
  onDiscard(messageId: string): void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    if (message.explanation === undefined) return;
    void navigator.clipboard.writeText(message.explanation).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [message.explanation]);

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
        <div className="chat-message__explanation">
          <MarkdownText>{message.explanation}</MarkdownText>
        </div>
      )}
      <DiagnosticsList diagnostics={message.diagnostics} />
      {!message.pending && message.outcome === undefined ? (
        <div className="chat-message__actions">
          {message.explanation !== undefined ? (
            <button type="button" className="chip" onClick={handleCopy}>
              {copied ? 'Copied' : 'Copy'}
            </button>
          ) : null}
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
  onAccept(source: string, actionId?: string): void;
  onDiscard(messageId: string): void;
}) {
  const [showDiff, setShowDiff] = useState(false);
  const hasSourcePreviews = (message.previewFiles?.length ?? 0) > 0;
  const hasCompilation = (message.compilationFiles?.length ?? 0) > 0;

  return (
    <div className="chat-message chat-message--assistant">
      <h2 className="chat-message__title">
        {hasCompilation ? 'Compilation preview' : 'AI generated source'}
      </h2>
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
          {hasSourcePreviews ? (
            <div className="ai-source-previews">
              {message.previewFiles?.map((file) => (
                <section key={file.path}>
                  <h3>{file.path}</h3>
                  {showDiff ? (
                    <DiffViewer
                      original={file.before_text}
                      modified={file.after_text}
                    />
                  ) : (
                    <SourcePreview source={file.after_text} />
                  )}
                </section>
              ))}
            </div>
          ) : message.source === undefined ? (
            !hasCompilation ? (
              <p className="chat-message__pending">No source generated</p>
            ) : null
          ) : showDiff ? (
            <div className="chat-message__diff">
              <DiffViewer original={activeFileContent} modified={message.source} />
            </div>
          ) : (
            <SourcePreview source={message.source} />
          )}
          {hasCompilation ? (
            <div className="ai-compilation-preview">
              {message.compilationFiles?.map((file) => (
                <section key={file.destination}>
                  <h3>{file.destination}</h3>
                  <pre>{file.after_text ?? `Binary artifact (${file.after_hash})`}</pre>
                </section>
              ))}
            </div>
          ) : null}
          <AssumptionsList assumptions={message.assumptions} />
          <AffectedDefinitionsList affected={message.affected} />
          <DiagnosticsList diagnostics={message.diagnostics} />
          <div className="chat-message__actions">
            {hasSourcePreviews ||
            (message.source !== undefined && activeFileContent !== message.source) ? (
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
              onClick={() =>
                onAccept(
                  message.source ?? message.previewFiles?.[0]?.after_text ?? '',
                  message.actionId,
                )
              }
              disabled={
                message.source === undefined &&
                !hasSourcePreviews &&
                !hasCompilation
              }
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
      tabIndex={0}
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

function AssumptionsList({ assumptions }: { assumptions: string[] | undefined }) {
  if (assumptions === undefined || assumptions.length === 0) return null;

  return (
    <div className="chat-message__assumptions">
      <span className="chat-message__assumptions-title">Assumptions</span>
      <ul>
        {assumptions.map((assumption, index) => (
          <li key={index}>{assumption}</li>
        ))}
      </ul>
    </div>
  );
}

function AffectedDefinitionsList({
  affected,
}: {
  affected: AssistantGenerateChatMessage['affected'] | undefined;
}) {
  if (affected === undefined || affected.length === 0) return null;

  return (
    <div className="chat-message__affected">
      <span className="chat-message__affected-title">Impacted Definitions</span>
      <ul>
        {affected.map((def, index) => (
          <li key={index}>
            <code>{def.ref}</code> ({def.status}): {def.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
