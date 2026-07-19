import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import './editor/monaco-environment';
import './style.css';

const root = document.getElementById('root');
if (root === null) {
  throw new Error('Missing React root');
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
