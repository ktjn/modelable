import {
  BrowserCompilerClient,
  BrowserCompilerError,
} from './client';
import type {
  BrowserArtifact,
  BrowserDiagnostic,
  BrowserSource,
} from './protocol';
import './style.css';

const client = new BrowserCompilerClient();
const source = element<HTMLTextAreaElement>('source');
const status = element<HTMLParagraphElement>('status');
const diagnostics = element<HTMLPreElement>('diagnostics');
const artifacts = element<HTMLPreElement>('artifacts');
const metrics = element<HTMLPreElement>('metrics');
const buttons = [
  element<HTMLButtonElement>('validate'),
  element<HTMLButtonElement>('format'),
  element<HTMLButtonElement>('generate'),
];
let initializationDuration: number | undefined;
let operationDuration: number | undefined;
let ready = false;
let busy = false;

if (new URLSearchParams(globalThis.location.search).get('test') === '1') {
  Object.defineProperty(globalThis, '__modelableBrowserCompiler', {
    configurable: true,
    value: client,
  });
}

function element<T extends HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (value === null) {
    throw new Error(`Missing required UI element: ${id}`);
  }
  return value as T;
}

function currentSource(): BrowserSource {
  return {
    uri: 'fixture:///playground.mdl',
    text: source.value,
    version: 1,
  };
}

function setState(
  state: 'initializing' | 'ready' | 'busy' | 'error',
  message: string,
): void {
  document.body.dataset.state = state;
  status.textContent = message;
}

function updateButtons(): void {
  for (const button of buttons) {
    button.disabled = !ready || busy;
  }
}

function updateMetrics(): void {
  const initialization =
    initializationDuration === undefined
      ? '— ms'
      : `${initializationDuration.toFixed(1)} ms`;
  const operation =
    operationDuration === undefined ? '— ms' : `${operationDuration.toFixed(1)} ms`;
  metrics.textContent = `initialization  ${initialization}\noperation       ${operation}`;
}

function renderDiagnostics(items: BrowserDiagnostic[]): void {
  diagnostics.textContent =
    items.length === 0
      ? 'No diagnostics.'
      : items
          .map((item) => {
            const location =
              item.line === null
                ? item.uri
                : `${item.uri}:${item.line}:${item.column ?? 1}`;
            return `${item.severity.toUpperCase()} ${item.code}  ${location}\n${item.message}`;
          })
          .join('\n\n');
}

function renderArtifacts(items: BrowserArtifact[]): void {
  artifacts.textContent =
    items.length === 0
      ? 'No artifacts generated.'
      : items
          .map((item) => `// ${item.path}\n${item.content}`)
          .join('\n\n');
}

function renderError(error: unknown): void {
  if (error instanceof BrowserCompilerError) {
    diagnostics.textContent = `${error.code}\n${error.message}`;
  } else {
    diagnostics.textContent = 'COMPILER_FAILED\nCompiler operation failed';
  }
}

async function runOperation(
  label: string,
  operation: () => Promise<void>,
): Promise<void> {
  if (!ready || busy) {
    return;
  }
  busy = true;
  updateButtons();
  setState('busy', `${label}…`);
  const started = performance.now();
  try {
    await operation();
    setState('ready', 'Compiler ready');
  } catch (error: unknown) {
    renderError(error);
    setState('error', 'Compiler operation failed');
  } finally {
    operationDuration = performance.now() - started;
    busy = false;
    updateButtons();
    updateMetrics();
  }
}

element<HTMLButtonElement>('validate').addEventListener('click', () => {
  void runOperation('Validating workspace', async () => {
    const result = await client.openWorkspace([currentSource()]);
    renderDiagnostics(result.diagnostics);
  });
});

element<HTMLButtonElement>('format').addEventListener('click', () => {
  void runOperation('Formatting source', async () => {
    const result = await client.formatSource(currentSource());
    renderDiagnostics(result.diagnostics);
    if (result.diagnostics.length === 0 && result.replacement_text !== null) {
      source.value = result.replacement_text;
    }
  });
});

element<HTMLButtonElement>('generate').addEventListener('click', () => {
  void runOperation('Generating JSON Schema', async () => {
    const result = await client.compileJsonSchema([currentSource()]);
    renderDiagnostics(result.diagnostics);
    renderArtifacts(result.artifacts);
  });
});

async function initialize(): Promise<void> {
  updateButtons();
  setState('initializing', 'Initializing compiler…');
  const started = performance.now();
  try {
    const fixtureRequest = fetch(
      new URL('fixtures/single-valid.mdl', globalThis.location.href),
    );
    const [, response] = await Promise.all([client.initialize(), fixtureRequest]);
    if (!response.ok) {
      throw new Error(`Fixture request failed: ${response.status}`);
    }
    source.value = await response.text();
    initializationDuration = performance.now() - started;
    ready = true;
    diagnostics.textContent = 'No diagnostics.';
    setState('ready', 'Compiler ready');
  } catch (error: unknown) {
    initializationDuration = performance.now() - started;
    renderError(error);
    setState('error', 'Compiler initialization failed');
  } finally {
    updateButtons();
    updateMetrics();
  }
}

void initialize();
