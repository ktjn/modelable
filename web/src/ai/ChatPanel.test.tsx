// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { ChatPanel } from './ChatPanel';
import { initialProviderState } from './provider-state';
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
    />,
  );

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
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Explain workspace' }));
  expect(onExplain).toHaveBeenCalled();

  await user.click(screen.getByRole('button', { name: 'Suggest projection' }));
  expect(onSuggestProjection).toHaveBeenCalled();
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
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Accept' }));
  expect(onAccept).toHaveBeenCalledWith('entity Order {}');
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
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Close' }));
  expect(onDiscard).toHaveBeenCalledWith('1');
});
