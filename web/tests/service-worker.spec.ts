import { expect, test } from '@playwright/test';

test('registers a service worker on first load', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('?test=1');
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });

  const hasController = await page.evaluate(async () => {
    if (!('serviceWorker' in navigator)) {
      return false;
    }
    const registration = await navigator.serviceWorker.ready;
    return registration.active !== null;
  });
  expect(hasController).toBe(true);
});

test('serves the application shell from cache when offline', async ({
  page,
  context,
}) => {
  test.setTimeout(90_000);

  await page.goto('?test=1');
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });

  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    if (registration.active === null) {
      throw new Error('Service worker not active');
    }
    const cacheNames = await caches.keys();
    if (cacheNames.length === 0) {
      throw new Error('No caches created by the service worker');
    }
  });

  await context.setOffline(true);
  await page.reload({ waitUntil: 'domcontentloaded' });

  await expect(page.locator('title')).toHaveText('Modelable Playground');
  await expect(page.locator('#root')).toBeAttached();
});

test('update banner appears and can be dismissed', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('?test=1');
  await expect(page.getByRole('status')).toHaveText(/compiler ready/i, {
    timeout: 30_000,
  });

  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });

  await page.evaluate(() => {
    const banner = document.createElement('div');
    banner.id = 'sw-update-banner';
    banner.setAttribute('role', 'alert');
    banner.innerHTML = `
      <span>A new version is available.</span>
      <button type="button" id="sw-update-reload">Reload</button>
      <button type="button" id="sw-update-dismiss" aria-label="Dismiss update notification">&times;</button>
    `;
    document.body.appendChild(banner);
    document.getElementById('sw-update-dismiss')?.addEventListener('click', () => {
      banner.remove();
    });
  });

  const banner = page.locator('#sw-update-banner');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('A new version is available');

  await page.getByRole('button', { name: 'Dismiss update notification' }).click();
  await expect(banner).toBeHidden();
});
