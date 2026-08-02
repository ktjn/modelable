import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { ErrorBoundary } from './ErrorBoundary';
import './editor/monaco-environment';
import { registerServiceWorker } from './sw-registration';
import './style.css';
import { initTheme } from './theme';

initTheme();

const root = document.getElementById('root');
if (root === null) {
  throw new Error('Missing React root');
}

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);

registerServiceWorker();
