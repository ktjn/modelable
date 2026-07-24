import { expect, type BrowserContext, type Page, type Request } from '@playwright/test';

const localOrigin = 'http://127.0.0.1:4173';

export function startLocalRequestAudit(context: BrowserContext): () => void {
  const offOriginRequests: string[] = [];
  const handleRequest = (request: Request): void => {
    const url = new URL(request.url());
    if (
      (url.protocol === 'http:' || url.protocol === 'https:') &&
      url.origin !== localOrigin
    ) {
      offOriginRequests.push(url.href);
    }
  };
  let finished = false;
  context.on('request', handleRequest);
  return () => {
    if (finished) {
      return;
    }
    finished = true;
    context.off('request', handleRequest);
    expect(
      offOriginRequests,
      'Every HTTP(S) request must stay on the local preview origin',
    ).toEqual([]);
  };
}

export function modelSource(page: Page) {
  return page.getByRole('textbox', { name: 'Model source' });
}

export function sourceOutput(page: Page) {
  return page.locator('.source-editor .view-lines');
}

export async function focusSourceEditor(page: Page): Promise<void> {
  await sourceOutput(page).click({
    position: { x: 8, y: 8 },
    force: true,
  });
  await modelSource(page).focus();
  await expect(modelSource(page)).toBeFocused();
}

export async function replaceSource(page: Page, text: string): Promise<void> {
  await focusSourceEditor(page);
  await page.keyboard.press('Control+a');
  await page.keyboard.press('Backspace');
  await expect(sourceOutput(page)).toHaveText('');
  await page.keyboard.type(text);
}

export async function waitForReady(page: Page): Promise<void> {
  await expect(page.locator('main.workbench')).not.toHaveAttribute('data-state', 'loading', {
    timeout: 90_000,
  });
}
