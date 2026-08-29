import { test as base, type Page } from '@playwright/test';
import { playwrightBaseURL } from '../playwright.config';

export const test = base.extend<{}, { sharedPage: Page }>({
  sharedPage: [
    async ({ browser }, use) => {
      const context = await browser.newContext({ baseURL: playwrightBaseURL });
      const page = await context.newPage();
      await use(page);
      await context.close();
    },
    { scope: 'worker' },
  ],
});

export { expect } from '@playwright/test';
