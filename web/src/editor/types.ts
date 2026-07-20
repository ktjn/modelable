import type { BrowserSource } from '../protocol';

export interface SourceEditorHandle {
  getSource(): BrowserSource;
  applyFormattedText(path: string, text: string): void;
  applyFormattedText(text: string): void;
  replaceText(text: string): void;
  focus(): void;
}
