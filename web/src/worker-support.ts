import {
  BROWSER_COMPILER_PROTOCOL_VERSION,
  type BrowserCompilerErrorCode,
  type BrowserCompilerFailure,
  type BrowserCompilerRequest,
  type BrowserCompilerResponse,
} from './protocol';

const LARK_WHEEL = 'lark-1.3.1-py3-none-any.whl';
const MODELABLE_WHEEL =
  /^modelable_browser-[A-Za-z0-9][A-Za-z0-9._!+-]*-py3-none-any\.whl$/;

interface PyProxyLike {
  destroy(): void;
}

interface PythonDispatchSuccess {
  ok: true;
  result: unknown;
}

interface PythonDispatchFailure {
  ok: false;
}

type PythonDispatchResponse =
  | PythonDispatchSuccess
  | PythonDispatchFailure;

export type PythonDispatcher = (
  method: string,
  payloadJson: string,
) => unknown;

export function sanitizedError(
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

export function failure(
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPyProxy(value: unknown): value is PyProxyLike {
  return (
    (typeof value === 'object' || typeof value === 'function') &&
    value !== null &&
    'destroy' in value &&
    typeof value.destroy === 'function'
  );
}

export function validateRuntimeManifest(
  manifest: unknown,
  manifestUrl: URL,
): string[] {
  if (!isRecord(manifest) || !Array.isArray(manifest.wheelUrls)) {
    throw new Error('Runtime manifest must contain wheel URLs');
  }
  if (manifest.wheelUrls.length !== 2) {
    throw new Error('Runtime manifest must contain exactly two wheel URLs');
  }
  if (!manifest.wheelUrls.every((value) => typeof value === 'string')) {
    throw new Error('Runtime manifest wheel URLs must be strings');
  }

  const pythonRoot = new URL('.', manifestUrl);
  const wheels = manifest.wheelUrls.map((value) => {
    const url = new URL(value, manifestUrl);
    if (
      url.origin !== pythonRoot.origin ||
      url.username !== '' ||
      url.password !== ''
    ) {
      throw new Error('Runtime wheels must use same-origin URLs');
    }
    if (
      !url.pathname.startsWith(pythonRoot.pathname) ||
      url.search !== '' ||
      url.hash !== ''
    ) {
      throw new Error('Runtime wheels must stay in the python directory');
    }
    const fileName = url.pathname.slice(pythonRoot.pathname.length);
    if (fileName.length === 0 || fileName.includes('/')) {
      throw new Error('Runtime wheels must stay in the python directory');
    }
    return { fileName, href: url.href };
  });

  if (new Set(wheels.map(({ href }) => href)).size !== wheels.length) {
    throw new Error('Runtime manifest wheel URLs must be distinct');
  }
  if (!wheels.some(({ fileName }) => fileName === LARK_WHEEL)) {
    throw new Error('Runtime manifest must contain the locked Lark wheel');
  }
  if (!wheels.some(({ fileName }) => MODELABLE_WHEEL.test(fileName))) {
    throw new Error('Runtime manifest must contain the generated Modelable wheel');
  }
  return wheels.map(({ href }) => href);
}

export function validatePythonRuntime(
  version: unknown,
  platform: unknown,
): void {
  if (version !== '3.14.2') {
    throw new Error('Browser runtime must use CPython 3.14.2');
  }
  if (platform !== 'emscripten') {
    throw new Error('Browser runtime must use the Emscripten platform');
  }
}

function parsePythonResponse(value: unknown): PythonDispatchResponse {
  if (typeof value !== 'string') {
    throw new TypeError('Python dispatcher did not return JSON text');
  }
  const parsed = JSON.parse(value) as unknown;
  if (
    !isRecord(parsed) ||
    typeof parsed.ok !== 'boolean' ||
    (parsed.ok && !Object.hasOwn(parsed, 'result'))
  ) {
    throw new TypeError('Python dispatcher returned an invalid response');
  }
  return parsed as unknown as PythonDispatchResponse;
}

export function dispatchPythonRequest(
  request: BrowserCompilerRequest,
  dispatcher: PythonDispatcher,
  onUnexpectedError: (error: unknown) => void = () => undefined,
): BrowserCompilerResponse {
  let payloadJson: string | undefined;
  try {
    payloadJson = JSON.stringify(request.payload);
  } catch {
    return failure(request.id, 'INVALID_REQUEST');
  }
  if (payloadJson === undefined) {
    return failure(request.id, 'INVALID_REQUEST');
  }

  let returned: unknown;
  try {
    returned = dispatcher(request.method, payloadJson);
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
    onUnexpectedError(error);
    return failure(request.id, 'COMPILER_FAILED');
  } finally {
    if (isPyProxy(returned)) {
      returned.destroy();
    }
  }
}
