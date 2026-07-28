import type {
  BrowserAffectedDefinition,
  BrowserChangedDefinition,
  BrowserConversationCompilationFile,
  BrowserConversationPreviewFile,
  BrowserDiagnostic,
} from '../protocol';

export interface ChatProviderInfo {
  provider: string;
  model: string;
}

export interface UserChatMessage {
  id: string;
  role: 'user';
  text: string;
}

export interface AssistantGenerateChatMessage {
  id: string;
  role: 'assistant';
  kind: 'generate';
  source?: string;
  diagnostics: BrowserDiagnostic[];
  providerInfo: ChatProviderInfo;
  pending: boolean;
  actionId?: string;
  assumptions: string[];
  changed: BrowserChangedDefinition[];
  affected: BrowserAffectedDefinition[];
  previewFiles?: BrowserConversationPreviewFile[];
  compilationFiles?: BrowserConversationCompilationFile[];
  outcome?: 'accepted' | 'discarded';
}

export interface AssistantExplainChatMessage {
  id: string;
  role: 'assistant';
  kind: 'explain';
  explanation?: string;
  diagnostics: BrowserDiagnostic[];
  providerInfo: ChatProviderInfo;
  pending: boolean;
  outcome?: 'accepted' | 'discarded';
}

export type AssistantChatMessage =
  | AssistantGenerateChatMessage
  | AssistantExplainChatMessage;

export type ChatMessage =
  | UserChatMessage
  | AssistantChatMessage;

export function isAssistantGenerateMessage(
  message: ChatMessage,
): message is AssistantGenerateChatMessage {
  return message.role === 'assistant' && message.kind === 'generate';
}

export function isAssistantExplainMessage(
  message: ChatMessage,
): message is AssistantExplainChatMessage {
  return message.role === 'assistant' && message.kind === 'explain';
}

export function generateChatMessageId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
