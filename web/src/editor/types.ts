import type { BrowserSource } from '../protocol';

export interface SourceEditorHandle {
  getSource(): BrowserSource;
  getPosition(): { uri: string; line: number; character: number } | null;
  applyFormattedText(path: string, text: string): void;
  applyFormattedText(text: string): void;
  replaceText(text: string): void;
  focus(): void;
}
