/// <reference types="emscripten" />
/// <reference types="vite/client" />

import { loadPyodide, type PyodideInterface } from 'pyodide';

import {
  BROWSER_COMPILER_PROTOCOL_VERSION,
  type BrowserCompilerFailure,
  type BrowserCompilerRequest,
  type BrowserCompilerResponse,
  isBrowserCompilerRequest,
} from './protocol';
import {
  dispatchPythonRequest,
  failure,
  sanitizedError,
  validateRuntimeManifest,
} from './worker-support';

interface PyProxyLike {
  destroy(): void;
}

interface CallablePyProxy extends PyProxyLike {
  (...args: unknown[]): unknown;
}

interface KeywordCallablePyProxy extends PyProxyLike {
  callKwargs(...args: unknown[]): unknown;
}

const scope = self;
let initialization: Promise<void> | undefined;
let dispatchBrowserRequest: CallablePyProxy | undefined;
let initializationFailure: BrowserCompilerFailure['error'] | undefined;
let ready = false;

function requestId(value: unknown): string {
  if (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    'id' in value &&
    typeof value.id === 'string' &&
    value.id.length > 0
  ) {
    return value.id;
  }
  return crypto.randomUUID();
}

function hasUnsupportedVersion(value: unknown): boolean {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    'protocolVersion' in value &&
    value.protocolVersion !== BROWSER_COMPILER_PROTOCOL_VERSION
  );
}

function developmentError(message: string, error: unknown): void {
  if (import.meta.env.DEV) {
    console.error(message, error);
  }
}

async function readWheelUrls(): Promise<string[]> {
  const manifestUrl = new URL(
    '../python/runtime-manifest.json',
    scope.location.href,
  );
  const response = await fetch(manifestUrl);
  if (!response.ok) {
    throw new Error(`Runtime manifest request failed: ${response.status}`);
  }
  return validateRuntimeManifest(await response.json(), manifestUrl);
}

async function initializeRuntime(): Promise<void> {
  let install: KeywordCallablePyProxy | undefined;
  let importedDispatch: CallablePyProxy | undefined;
  try {
    const pyodide: PyodideInterface = await loadPyodide({
      indexURL: new URL('../pyodide/', self.location.href).href,
    });
    await pyodide.loadPackage([
      'micropip',
      'pydantic',
      'jsonschema',
      'pyyaml',
    ]);
    const wheelUrls = await readWheelUrls();
    install = pyodide.pyimport('micropip.install') as KeywordCallablePyProxy;
    await install.callKwargs(wheelUrls, { deps: false });
    importedDispatch = pyodide.pyimport(
      'modelable.browser.dispatch_browser_request',
    ) as CallablePyProxy;
    dispatchBrowserRequest = importedDispatch;
    importedDispatch = undefined;
    ready = true;
  } finally {
    install?.destroy();
    importedDispatch?.destroy();
  }
}

async function ensureInitialized(): Promise<void> {
  if (initializationFailure !== undefined) {
    throw initializationFailure;
  }
  initialization ??= initializeRuntime().catch((error: unknown) => {
    developmentError('Browser compiler initialization failed', error);
    dispatchBrowserRequest?.destroy();
    dispatchBrowserRequest = undefined;
    ready = false;
    initializationFailure = sanitizedError('INITIALIZATION_FAILED');
    throw initializationFailure;
  });
  return initialization;
}

function dispatch(request: BrowserCompilerRequest): BrowserCompilerResponse {
  if (!ready || dispatchBrowserRequest === undefined) {
    return failure(request.id, 'INITIALIZATION_FAILED');
  }

  return dispatchPythonRequest(
    request,
    dispatchBrowserRequest,
    (error: unknown) =>
      developmentError('Browser compiler dispatch failed', error),
  );
}

scope.addEventListener(
  'message',
  async (event: MessageEvent<unknown>): Promise<void> => {
    const id = requestId(event.data);
    if (hasUnsupportedVersion(event.data)) {
      scope.postMessage(failure(id, 'UNSUPPORTED_PROTOCOL'));
      return;
    }
    if (!isBrowserCompilerRequest(event.data)) {
      scope.postMessage(failure(id, 'INVALID_REQUEST'));
      return;
    }

    const request = event.data;
    if (request.method === 'runtime.initialize') {
      try {
        await ensureInitialized();
        scope.postMessage({
          protocolVersion: BROWSER_COMPILER_PROTOCOL_VERSION,
          id: request.id,
          ok: true,
          result: null,
        } satisfies BrowserCompilerResponse);
      } catch {
        scope.postMessage(
          failure(
            request.id,
            initializationFailure ?? 'INITIALIZATION_FAILED',
          ),
        );
      }
      return;
    }
    scope.postMessage(dispatch(request));
  },
);
