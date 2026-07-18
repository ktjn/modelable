/// <reference types="emscripten" />
/// <reference types="vite/client" />

import { loadPyodide, type PyodideInterface } from 'pyodide';

import {
  BROWSER_COMPILER_PROTOCOL_VERSION,
  type BrowserCompilerErrorCode,
  type BrowserCompilerFailure,
  type BrowserCompilerRequest,
  type BrowserCompilerResponse,
  isBrowserCompilerRequest,
} from './protocol';

interface PyProxyLike {
  destroy(): void;
}

interface CallablePyProxy extends PyProxyLike {
  (...args: unknown[]): unknown;
}

interface KeywordCallablePyProxy extends PyProxyLike {
  callKwargs(...args: unknown[]): unknown;
}

interface RuntimeManifest {
  wheelUrls: unknown;
}

interface PythonDispatchSuccess {
  ok: true;
  result: unknown;
}

interface PythonDispatchFailure {
  ok: false;
  error?: unknown;
}

type PythonDispatchResponse =
  | PythonDispatchSuccess
  | PythonDispatchFailure;

const scope = self;
let initialization: Promise<void> | undefined;
let dispatchBrowserRequest: CallablePyProxy | undefined;
let initializationFailure: BrowserCompilerFailure['error'] | undefined;
let ready = false;

function sanitizedError(
  code: BrowserCompilerErrorCode,
): BrowserCompilerFailure['error'] {
  const messages: Record<BrowserCompilerErrorCode, string> = {
    INITIALIZATION_FAILED: 'Compiler runtime initialization failed',
    INVALID_REQUEST: 'Browser compiler request is invalid',
    UNSUPPORTED_PROTOCOL: 'Browser compiler protocol version is unsupported',
    COMPILER_FAILED: 'Compiler request failed',
  };
  return { code, message: messages[code] };
}

function failure(
  id: string,
  codeOrError:
    | BrowserCompilerErrorCode
    | BrowserCompilerFailure['error'],
): BrowserCompilerFailure {
  return {
    protocolVersion: BROWSER_COMPILER_PROTOCOL_VERSION,
    id,
    ok: false,
    error:
      typeof codeOrError === 'string'
        ? sanitizedError(codeOrError)
        : codeOrError,
  };
}

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

function isPyProxy(value: unknown): value is PyProxyLike {
  return (
    (typeof value === 'object' || typeof value === 'function') &&
    value !== null &&
    'destroy' in value &&
    typeof value.destroy === 'function'
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
  const manifest = (await response.json()) as RuntimeManifest;
  if (
    !Array.isArray(manifest.wheelUrls) ||
    !manifest.wheelUrls.every((url) => typeof url === 'string')
  ) {
    throw new Error('Runtime manifest has invalid wheel URLs');
  }

  const expectedRoot = new URL('../python/', scope.location.href);
  return manifest.wheelUrls.map((value) => {
    const url = new URL(value, manifestUrl);
    if (
      url.origin !== expectedRoot.origin ||
      !url.pathname.startsWith(expectedRoot.pathname)
    ) {
      throw new Error('Runtime manifest contains a non-local wheel URL');
    }
    return url.href;
  });
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

function parsePythonResponse(value: unknown): PythonDispatchResponse {
  if (typeof value !== 'string') {
    throw new TypeError('Python dispatcher did not return JSON text');
  }
  const parsed = JSON.parse(value) as unknown;
  if (
    typeof parsed !== 'object' ||
    parsed === null ||
    Array.isArray(parsed) ||
    !('ok' in parsed) ||
    typeof parsed.ok !== 'boolean'
  ) {
    throw new TypeError('Python dispatcher returned an invalid response');
  }
  if (parsed.ok && !('result' in parsed)) {
    throw new TypeError('Python dispatcher omitted its result');
  }
  return parsed as PythonDispatchResponse;
}

function dispatch(request: BrowserCompilerRequest): BrowserCompilerResponse {
  if (!ready || dispatchBrowserRequest === undefined) {
    return failure(request.id, 'INITIALIZATION_FAILED');
  }

  let returned: unknown;
  try {
    returned = dispatchBrowserRequest(
      request.method,
      JSON.stringify(request.payload),
    );
    const parsed = parsePythonResponse(returned);
    if (!parsed.ok) {
      return failure(request.id, 'INVALID_REQUEST');
    }
    return {
      protocolVersion: BROWSER_COMPILER_PROTOCOL_VERSION,
      id: request.id,
      ok: true,
      result: parsed.result,
    };
  } catch (error: unknown) {
    developmentError('Browser compiler dispatch failed', error);
    return failure(request.id, 'COMPILER_FAILED');
  } finally {
    if (isPyProxy(returned)) {
      returned.destroy();
    }
  }
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
