// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import indexHtml from '../index.html?raw';
import { App } from './App';
import { BrowserCompilerError } from './client';
import type {
  BrowserCompileResult,
  BrowserFormatResult,
  BrowserSource,
  BrowserWorkspaceResult,
} from './protocol';

const sourceEditorSpies = vi.hoisted(() => ({
  applyFormattedText: vi.fn(),
}));

vi.mock('./editor/SourceEditor', async () => {
  const {
    forwardRef,
    useImperativeHandle,
    useRef,
    useState,
  } = await import('react');
  return {
    SourceEditor: forwardRef(function FakeSourceEditor(
      {
        initialValue,
        onRevisionChange,
      }: {
        initialValue: string;
        onRevisionChange(version: number): void;
      },
      ref,
    ) {
      const [value, setValue] = useState(initialValue);
      const valueRef = useRef(value);
      const versionRef = useRef(1);

      valueRef.current = value;
      useImperativeHandle(ref, () => ({
        getSource(): BrowserSource {
          return {
            uri: 'file:///main.mdl',
            text: valueRef.current,
            version: versionRef.current,
          };
        },
        applyFormattedText(text: string) {
          sourceEditorSpies.applyFormattedText(text);
          valueRef.current = text;
          setValue(text);
          versionRef.current += 1;
          onRevisionChange(versionRef.current);
        },
        replaceText(text: string) {
          valueRef.current = text;
          setValue(text);
          versionRef.current += 1;
          onRevisionChange(versionRef.current);
        },
        focus() {},
      }));

      return (
        <textarea
          aria-label="Model source"
          value={value}
          onChange={(event) => {
            valueRef.current = event.target.value;
            setValue(event.target.value);
            versionRef.current += 1;
            onRevisionChange(versionRef.current);
          }}
        />
      );
    }),
  };
});

vi.mock('./editor/ArtifactEditor', () => ({
  ArtifactEditor: ({ value }: { value: string }) => (
    <pre aria-label="Artifact output">{value}</pre>
  ),
}));

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function latestRequest<T>(requests: Deferred<T>[]): Deferred<T> {
  const request = requests.at(-1);
  if (request === undefined) {
    throw new Error('Expected a pending compiler request');
  }
  return request;
}

class FakeCompilerClient {
  readonly initialization = deferred<void>();
  readonly workspaceRequests: Deferred<BrowserWorkspaceResult>[] = [];
  readonly formatRequests: Deferred<BrowserFormatResult>[] = [];
  readonly compileRequests: Deferred<BrowserCompileResult>[] = [];

  readonly initialize = vi.fn(() => this.initialization.promise);
  readonly openWorkspace = vi.fn((_sources: BrowserSource[]) => {
    const request = deferred<BrowserWorkspaceResult>();
    this.workspaceRequests.push(request);
    return request.promise;
  });
  readonly formatSource = vi.fn((_source: BrowserSource) => {
    const request = deferred<BrowserFormatResult>();
    this.formatRequests.push(request);
    return request.promise;
  });
  readonly compileJsonSchema = vi.fn((_sources: BrowserSource[]) => {
    const request = deferred<BrowserCompileResult>();
    this.compileRequests.push(request);
    return request.promise;
  });
  readonly dispose = vi.fn();
}

const documentDiagnostic = {
  code: 'MODELABLE_TEST',
  severity: 'error',
  message: 'Customer is invalid',
  uri: 'file:///main.mdl',
  line: null,
  column: null,
  end_line: null,
  end_column: null,
};

async function initialize(client: FakeCompilerClient): Promise<void> {
  await act(async () => {
    client.initialization.resolve();
    await client.initialization.promise;
  });
}

afterEach(() => {
  cleanup();
  sourceEditorSpies.applyFormattedText.mockReset();
});

describe('App', () => {
  test('disables actions during initialization and enables them after success', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} now={() => 10} />);

    for (const name of ['Validate', 'Format', 'Generate']) {
      expect(
        (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
      ).toBe(true);
    }
    expect(screen.getByRole('status').textContent).toMatch(
      /initializing compiler/i,
    );

    await initialize(client);

    for (const name of ['Validate', 'Format', 'Generate']) {
      expect(
        (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
      ).toBe(false);
    }
    expect(screen.getByRole('status').textContent).toMatch(/compiler ready/i);
  });

  test('disables duplicate actions while one request is pending', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));

    expect(client.openWorkspace).toHaveBeenCalledTimes(1);
    for (const name of ['Validate', 'Format', 'Generate']) {
      expect(
        (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
      ).toBe(true);
    }
  });

  test('renders validation diagnostics from the current revision', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} now={() => 20} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    const request = latestRequest(client.workspaceRequests);
    await act(async () => {
      request.resolve({
        diagnostics: [documentDiagnostic],
        source_hashes: {},
      });
      await request.promise;
    });

    expect(screen.getByText('Customer is invalid')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toMatch(/1 diagnostic/i);
  });

  test('ignores a validation result after the source revision changes', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Model source' }), {
      target: { value: 'record Edited {}' },
    });
    const request = latestRequest(client.workspaceRequests);
    await act(async () => {
      request.resolve({
        diagnostics: [documentDiagnostic],
        source_hashes: {},
      });
      await request.promise;
    });

    expect(screen.queryByText('Customer is invalid')).toBeNull();
  });

  test('applies formatted text from a current successful result', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Format' }));
    const request = latestRequest(client.formatRequests);
    await act(async () => {
      request.resolve({
        diagnostics: [],
        replacement_text: 'record Customer {\n}\n',
      });
      await request.promise;
    });

    expect(sourceEditorSpies.applyFormattedText).toHaveBeenCalledWith(
      'record Customer {\n}\n',
    );
  });

  test('retains and marks the old artifact stale after failed generation', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    const initialRequest = latestRequest(client.compileRequests);
    await act(async () => {
      initialRequest.resolve({
        diagnostics: [],
        artifacts: [
          {
            path: 'customer.schema.json',
            media_type: 'application/schema+json',
            content: '{"title":"Customer"}',
            source_refs: ['file:///main.mdl'],
          },
        ],
      });
      await initialRequest.promise;
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Model source' }), {
      target: { value: 'record Edited {}' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    const failedRequest = latestRequest(client.compileRequests);
    await act(async () => {
      failedRequest.resolve({
        diagnostics: [documentDiagnostic],
        artifacts: [],
      });
      await failedRequest.promise;
    });

    expect(screen.getByLabelText('Artifact output').textContent).toBe(
      '{"title":"Customer"}',
    );
    expect(screen.getByText(/artifact is stale/i)).toBeTruthy();
  });

  test('retries initialization with a fresh client', async () => {
    const firstClient = new FakeCompilerClient();
    const secondClient = new FakeCompilerClient();
    const createClient = vi
      .fn()
      .mockReturnValueOnce(firstClient)
      .mockReturnValueOnce(secondClient);
    render(<App createClient={createClient} />);

    await act(async () => {
      firstClient.initialization.reject(
        new BrowserCompilerError(
          'INITIALIZATION_FAILED',
          'Python runtime unavailable',
        ),
      );
      await expect(firstClient.initialization.promise).rejects.toThrow(
        'Python runtime unavailable',
      );
    });

    fireEvent.click(screen.getByRole('button', { name: 'Retry compiler' }));

    expect(firstClient.dispose).toHaveBeenCalled();
    expect(createClient).toHaveBeenCalledTimes(2);
    await initialize(secondClient);
    expect(screen.getByRole('status').textContent).toMatch(/compiler ready/i);
  });

  test('provides a focusable target for the skip link', () => {
    const client = new FakeCompilerClient();
    const template = document.createElement('template');
    template.innerHTML = indexHtml;
    const skipLink =
      template.content.querySelector<HTMLAnchorElement>('.skip-link');

    render(<App createClient={() => client} />);

    const href = skipLink?.getAttribute('href');
    expect(href).toBe('#source-editor');
    const target = document.querySelector<HTMLElement>(href ?? '');
    expect(target).toBeTruthy();
    expect(target?.tabIndex).toBe(-1);

    target?.focus();
    expect(document.activeElement).toBe(target);
  });
});
