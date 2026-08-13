import type { BrowserSource } from '../protocol';

export interface SourceEditorHandle {
  getSource(): BrowserSource;
  getPosition(): { uri: string; line: number; character: number } | null;
  applyFormattedText(path: string, text: string): void;
  applyFormattedText(text: string): void;
  replaceText(text: string): void;
  focus(): void;
  /**
   * Switches to `path` and moves the cursor to `line`/`column`, both
   * 1-based (Monaco-native), matching how BrowserDiagnostic reports
   * position -- NOT the 0-based line/character convention getPosition()
   * and LSP-derived source ranges use elsewhere in this file.
   */
  revealPosition(path: string, line: number, column: number): void;
}
