export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) {
    return;
  }
  window.addEventListener('load', () => {
    void import('virtual:pwa-register').then(({ registerSW }) => {
      const updateSW = registerSW({
        onNeedRefresh() {
          showUpdateBanner(updateSW);
        },
      });
    });
  });
}

function showUpdateBanner(updateSW: (reloadPage?: boolean) => Promise<void>): void {
  if (document.getElementById('sw-update-banner')) {
    return;
  }
  const banner = document.createElement('div');
  banner.id = 'sw-update-banner';
  banner.setAttribute('role', 'alert');
  banner.innerHTML = `
    <span>A new version is available.</span>
    <button type="button" id="sw-update-reload">Reload</button>
    <button type="button" id="sw-update-dismiss" aria-label="Dismiss update notification">&times;</button>
  `;
  document.body.appendChild(banner);

  document.getElementById('sw-update-reload')?.addEventListener('click', () => {
    void updateSW(true);
  });
  document.getElementById('sw-update-dismiss')?.addEventListener('click', () => {
    banner.remove();
  });
}
