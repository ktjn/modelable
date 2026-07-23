import type { LlmProvider, ProviderStatus } from './types';

export interface ProviderState {
  status: ProviderStatus;
  provider: LlmProvider | null;
  progress: number;
  message: string;
  error: string | null;
}

export const initialProviderState: ProviderState = {
  status: 'idle',
  provider: null,
  progress: 0,
  message: '',
  error: null,
};

export type ProviderAction =
  | { type: 'detect_start' }
  | { type: 'detect_unsupported' }
  | { type: 'detect_available' }
  | { type: 'download_start'; provider: LlmProvider }
  | { type: 'download_progress'; progress: number; message: string }
  | { type: 'ready' }
  | { type: 'error'; message: string }
  | { type: 'reset' };

export function providerStateReducer(
  state: ProviderState,
  action: ProviderAction,
): ProviderState {
  switch (action.type) {
    case 'detect_start':
      return { ...state, status: 'detecting', error: null };
    case 'detect_unsupported':
      return { ...state, status: 'unsupported', error: null };
    case 'detect_available':
      return { ...state, status: 'idle', error: null };
    case 'download_start':
      return {
        ...state,
        status: 'downloading',
        provider: action.provider,
        progress: 0,
        message: 'Starting model download…',
        error: null,
      };
    case 'download_progress':
      return {
        ...state,
        progress: action.progress,
        message: action.message,
      };
    case 'ready':
      return { ...state, status: 'ready', progress: 1, message: 'Model ready' };
    case 'error':
      return { ...state, status: 'error', error: action.message };
    case 'reset':
      return { ...initialProviderState };
  }
}

export function providerStatusLabel(state: ProviderState): string {
  switch (state.status) {
    case 'idle':
      return 'AI ready to download';
    case 'detecting':
      return 'Detecting WebGPU…';
    case 'downloading':
      return state.message;
    case 'ready':
      return 'AI model ready';
    case 'error':
      return `AI error: ${state.error ?? 'unknown'}`;
    case 'unsupported':
      return 'WebGPU not available';
  }
}
