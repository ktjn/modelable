export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) {
    return;
  }
  window.addEventListener('load', () => {
    void import('virtual:pwa-register').then(({ registerSW }) => {
      registerSW();
    });
  });
}
