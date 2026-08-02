import { expect, test } from '@playwright/test';
import { waitForReady } from './helpers';

test('registers a service worker on first load', async ({ page }) => {

  await page.goto('?test=1');
  await waitForReady(page);

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
  await waitForReady(page);

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

  await expect(page).toHaveTitle('Modelable Playground');
  await expect(page.locator('#root')).toBeAttached();
});

test('service worker controls the page after load', async ({ page }) => {
  await page.goto('?test=1');
  await waitForReady(page);

  const controllerUrl = await page.evaluate(
    () => navigator.serviceWorker.controller?.scriptURL,
  );
  expect(controllerUrl).toContain('/modelable/playground/sw.js');
});
