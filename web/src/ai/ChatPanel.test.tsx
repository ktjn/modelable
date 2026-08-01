// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { ChatPanel } from './ChatPanel';
import { initialProviderState } from './provider-state';
import { DEFAULT_MODELS } from './webgpu-provider';
import type { ChatMessage } from './chat-types';

vi.mock('monaco-editor/esm/vs/editor/editor.api.js', () => ({
  editor: {
    colorize: vi.fn(async (code: string) => code),
  },
}));

const readyProviderState = {
  ...initialProviderState,
  status: 'ready' as const,
  provider: { id: 'heuristic', model: 'rule' } as unknown as import('./types').LlmProvider,
};

const emptyMessages: ChatMessage[] = [];

afterEach(cleanup);

test('renders onboarding when no provider is ready', () => {
  render(
    <ChatPanel
      messages={emptyMessages}
      activeFileContent=""
      aiState={initialProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={vi.fn()}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  expect(screen.getByRole('combobox', { name: /model/i })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Download AI model' })).toBeTruthy();
});

test('sends a message from the composer', async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();
  render(
    <ChatPanel
      messages={emptyMessages}
      activeFileContent=""
      aiState={readyProviderState}
      actionsDisabled={false}
      onSend={onSend}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={vi.fn()}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  await user.type(
    screen.getByPlaceholderText('e.g. Add a creditScore field to Customer'),
    'Add Order',
  );
  await user.click(screen.getByRole('button', { name: 'Send' }));

  expect(onSend).toHaveBeenCalledWith('Add Order');
});

test('calls quick action chips', async () => {
  const user = userEvent.setup();
  const onExplain = vi.fn();
  const onSuggestProjection = vi.fn();
  render(
    <ChatPanel
      messages={emptyMessages}
      activeFileContent=""
      aiState={readyProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={onExplain}
      onSuggestProjection={onSuggestProjection}
      onAccept={vi.fn()}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Explain workspace' }));
  expect(onExplain).toHaveBeenCalled();

  await user.click(screen.getByRole('button', { name: 'Suggest projection' }));
  expect(onSuggestProjection).toHaveBeenCalled();
});

test('renders documentation citations as safe links', () => {
  render(
    <ChatPanel
      messages={[{
        id: 'docs-1',
        role: 'assistant',
        kind: 'docs',
        answer: 'Use the compiler command.',
        citations: [
          { label: 'S1 guide.md#compile', url: 'https://example.test/guide' },
          { label: 'S2 unsafe', url: 'javascript:alert(1)' },
        ],
        diagnostics: [],
        providerInfo: { provider: 'heuristic', model: 'rule' },
        pending: false,
      }]}
      activeFileContent=""
      aiState={readyProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={vi.fn()}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  expect(screen.getByRole('link', { name: 'S1 guide.md#compile' }).getAttribute('href')).toBe(
    'https://example.test/guide',
  );
  expect(screen.getByText('S2 unsafe')).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'S2 unsafe' })).toBeNull();
});

test('accepts generated source', async () => {
  const user = userEvent.setup();
  const onAccept = vi.fn();
  const messages: ChatMessage[] = [
    {
      id: '1',
      role: 'assistant',
      kind: 'generate',
      source: 'entity Order {}',
      diagnostics: [],
      providerInfo: { provider: 'heuristic', model: 'rule' },
      pending: false,
      assumptions: [],
      changed: [],
      affected: [],
    },
  ];
  render(
    <ChatPanel
      messages={messages}
      activeFileContent=""
      aiState={readyProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={onAccept}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Accept' }));
  expect(onAccept).toHaveBeenCalledWith('entity Order {}', undefined);
});

test('previews and accepts compilation artifacts', async () => {
  const user = userEvent.setup();
  const onAccept = vi.fn();
  const messages: ChatMessage[] = [
    {
      id: '1',
      role: 'assistant',
      kind: 'generate',
      diagnostics: [],
      providerInfo: { provider: 'simulator', model: 'semantic-v1' },
      pending: false,
      actionId: 'compile-1',
      assumptions: [],
      changed: [],
      affected: [],
      compilationFiles: [
        {
          destination: 'dist/customer.schema.json',
          media_type: 'application/json',
          after_text: '{"type":"object"}',
          after_hash: 'abc123',
        },
      ],
    },
  ];
  render(
    <ChatPanel
      messages={messages}
      activeFileContent=""
      aiState={readyProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={onAccept}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  expect(screen.getByText('dist/customer.schema.json')).toBeTruthy();
  expect(screen.getByText('{"type":"object"}')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Accept' }));
  expect(onAccept).toHaveBeenCalledWith('', 'compile-1');
});

test('renders every source file in a multi-file preview', async () => {
  const user = userEvent.setup();
  const onAccept = vi.fn();
  const messages: ChatMessage[] = [
    {
      id: '1',
      role: 'assistant',
      kind: 'generate',
      diagnostics: [],
      providerInfo: { provider: 'simulator', model: 'semantic-v1' },
      pending: false,
      actionId: 'change-1',
      assumptions: [],
      changed: [],
      affected: [],
      previewFiles: [
        {
          path: 'a.mdl',
          existed_before: true,
          before_text: 'domain a {}',
          after_text: 'domain a { owner: "a" }',
        },
        {
          path: 'b.mdl',
          existed_before: true,
          before_text: 'domain b {}',
          after_text: 'domain b { owner: "b" }',
        },
      ],
    },
  ];
  render(
    <ChatPanel
      messages={messages}
      activeFileContent="unrelated active source"
      aiState={readyProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={onAccept}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  expect(screen.getByText('a.mdl')).toBeTruthy();
  expect(screen.getByText('b.mdl')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Accept' }));
  expect(onAccept).toHaveBeenCalledWith(
    'domain a { owner: "a" }',
    'change-1',
  );
});

test('discards a message', async () => {
  const user = userEvent.setup();
  const onDiscard = vi.fn();
  const messages: ChatMessage[] = [
    {
      id: '1',
      role: 'assistant',
      kind: 'explain',
      explanation: 'An explanation',
      diagnostics: [],
      providerInfo: { provider: 'heuristic', model: 'rule' },
      pending: false,
    },
  ];
  render(
    <ChatPanel
      messages={messages}
      activeFileContent=""
      aiState={readyProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={vi.fn()}
      onDiscard={onDiscard}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={DEFAULT_MODELS}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Close' }));
  expect(onDiscard).toHaveBeenCalledWith('1');
});
