// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import indexHtml from '../index.html?raw';
import { App } from './App';
import { BrowserCompilerError } from './client';
import { MAX_IMPORT_BYTES } from './files';
import type {
  BrowserCompileResult,
  BrowserFormatResult,
  BrowserSource,
  BrowserWorkspaceResult,
} from './protocol';

const sourceEditorSpies = vi.hoisted(() => ({
  applyFormattedText: vi.fn(),
  focus: vi.fn(),
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
        focus() {
          sourceEditorSpies.focus();
        },
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

function fileWithDeferredText(
  name: string,
  text: Deferred<string>,
): File {
  const file = new File([], name);
  Object.defineProperty(file, 'text', {
    value: vi.fn(() => text.promise),
  });
  return file;
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

function chooseSourceFile(file: File): void {
  const input = document.querySelector<HTMLInputElement>(
    'input[type="file"]',
  );
  if (input === null) {
    throw new Error('Expected a source file input');
  }
  fireEvent.change(input, { target: { files: [file] } });
}

async function importSource(
  file: File,
  expectedText: string,
): Promise<void> {
  chooseSourceFile(file);
  await waitFor(() => {
    expect(
      (
        screen.getByRole('textbox', {
          name: 'Model source',
        }) as HTMLTextAreaElement
      ).value,
    ).toBe(expectedText);
  });
}

async function generateArtifacts(
  client: FakeCompilerClient,
  artifacts: BrowserCompileResult['artifacts'],
): Promise<void> {
  fireEvent.click(
    screen.getByRole('button', { name: 'Generate JSON Schema' }),
  );
  const request = latestRequest(client.compileRequests);
  await act(async () => {
    request.resolve({ diagnostics: [], artifacts });
    await request.promise;
  });
}

afterEach(() => {
  cleanup();
  sourceEditorSpies.applyFormattedText.mockReset();
  sourceEditorSpies.focus.mockReset();
});

describe('App', () => {
  test('disables actions during initialization and enables them after success', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} now={() => 10} />);

    for (const name of ['Validate', 'Format', 'Generate JSON Schema']) {
      expect(
        (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
      ).toBe(true);
    }
    expect(screen.getByRole('status').textContent).toMatch(
      /initializing compiler/i,
    );

    await initialize(client);

    for (const name of ['Validate', 'Format', 'Generate JSON Schema']) {
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
    for (const name of ['Validate', 'Format', 'Generate JSON Schema']) {
      expect(
        (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
      ).toBe(true);
    }
  });

  test('runs enabled compiler commands through their keyboard shortcuts', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.keyDown(window, {
      key: 'Enter',
      code: 'Enter',
      ctrlKey: true,
      shiftKey: true,
    });
    expect(client.openWorkspace).toHaveBeenCalledTimes(1);
    await act(async () => {
      const request = latestRequest(client.workspaceRequests);
      request.resolve({ diagnostics: [], source_hashes: {} });
      await request.promise;
    });

    fireEvent.keyDown(window, {
      key: 'F',
      code: 'KeyF',
      altKey: true,
      shiftKey: true,
    });
    expect(client.formatSource).toHaveBeenCalledTimes(1);
    await act(async () => {
      const request = latestRequest(client.formatRequests);
      request.resolve({ diagnostics: [], replacement_text: null });
      await request.promise;
    });

    fireEvent.keyDown(window, {
      key: 'Enter',
      code: 'Enter',
      ctrlKey: true,
    });
    expect(client.compileJsonSchema).toHaveBeenCalledTimes(1);
  });

  test('ignores keyboard shortcuts while the compiler is loading or working', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);

    fireEvent.keyDown(window, {
      key: 'Enter',
      code: 'Enter',
      ctrlKey: true,
      shiftKey: true,
    });
    expect(client.openWorkspace).not.toHaveBeenCalled();

    await initialize(client);
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    expect(client.openWorkspace).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, {
      key: 'F',
      code: 'KeyF',
      altKey: true,
      shiftKey: true,
    });
    fireEvent.keyDown(window, {
      key: 'Enter',
      code: 'Enter',
      ctrlKey: true,
    });
    expect(client.formatSource).not.toHaveBeenCalled();
    expect(client.compileJsonSchema).not.toHaveBeenCalled();
  });

  test('exposes visible toolbar names and command shortcuts', () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);

    const shortcuts = new Map([
      ['Validate', 'Control+Shift+Enter Meta+Shift+Enter'],
      ['Format', 'Shift+Alt+F'],
      ['Generate JSON Schema', 'Control+Enter Meta+Enter'],
    ]);
    for (const button of screen.getAllByRole('button')) {
      expect(button.textContent?.trim()).not.toBe('');
      const expectedShortcut = shortcuts.get(button.textContent?.trim() ?? '');
      if (expectedShortcut !== undefined) {
        expect(button.getAttribute('aria-keyshortcuts')).toBe(expectedShortcut);
      }
    }
    expect(shortcuts.size).toBe(3);
  });

  test('announces operation failures as alerts', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    const request = latestRequest(client.workspaceRequests);
    await act(async () => {
      request.reject(
        new BrowserCompilerError(
          'INVALID_REQUEST',
          'Validation request failed',
        ),
      );
      await expect(request.promise).rejects.toThrow(
        'Validation request failed',
      );
    });

    expect(screen.getByRole('alert').textContent).toMatch(
      /validation request failed/i,
    );
    expect(screen.queryByRole('status')).toBeNull();

    fireEvent.change(screen.getByRole('textbox', { name: 'Model source' }), {
      target: { value: 'record Recovered {}' },
    });
    expect(screen.getByRole('status').textContent).toMatch(/source changed/i);
    expect(screen.queryByRole('alert')).toBeNull();
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

  test('imports source and clears diagnostics', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
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

    await importSource(
      new File(['record Customer {}'], 'customer.mdl', {
        type: 'text/plain',
      }),
      'record Customer {}',
    );

    expect(
      (screen.getByRole('textbox', {
        name: 'Model source',
      }) as HTMLTextAreaElement).value,
    ).toBe('record Customer {}');
    expect(screen.queryByText('Customer is invalid')).toBeNull();
  });

  test('shows an unsupported import error and recovers on a valid import', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);
    const editor = screen.getByRole('textbox', { name: 'Model source' });
    const initialText = (editor as HTMLTextAreaElement).value;

    chooseSourceFile(new File(['not source'], 'customer.json'));

    expect((await screen.findByRole('alert')).textContent).toMatch(
      /choose a \.mdl or \.txt source file/i,
    );
    expect((editor as HTMLTextAreaElement).value).toBe(initialText);
    expect(screen.getByRole('status').textContent).toMatch(
      /compiler ready/i,
    );

    chooseSourceFile(
      new File(['record Customer {}'], 'customer.mdl'),
    );
    await waitFor(() => {
      expect((editor as HTMLTextAreaElement).value).toBe(
        'record Customer {}',
      );
    });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('shows an oversized import error without replacing source', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);
    const editor = screen.getByRole('textbox', { name: 'Model source' });
    const initialText = (editor as HTMLTextAreaElement).value;

    chooseSourceFile(
      new File(
        [new Uint8Array(MAX_IMPORT_BYTES + 1)],
        'large.mdl',
      ),
    );

    expect((await screen.findByRole('alert')).textContent).toMatch(
      /1 MiB or smaller/i,
    );
    expect((editor as HTMLTextAreaElement).value).toBe(initialText);
    expect(screen.getByRole('status').textContent).toMatch(
      /compiler ready/i,
    );
  });

  test('sanitizes unreadable import errors without replacing source', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);
    const editor = screen.getByRole('textbox', { name: 'Model source' });
    const initialText = (editor as HTMLTextAreaElement).value;
    const file = new File(['source'], 'customer.mdl');
    Object.defineProperty(file, 'text', {
      value: vi.fn().mockRejectedValue(
        new Error('sensitive C:\\private\\source.mdl failure'),
      ),
    });

    chooseSourceFile(file);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(
      /could not read the selected source file/i,
    );
    expect(alert.textContent).not.toMatch(/sensitive|private/i);
    expect((editor as HTMLTextAreaElement).value).toBe(initialText);
    expect(screen.getByRole('status').textContent).toMatch(
      /compiler ready/i,
    );
  });

  test('ignores an older import that resolves after the latest import', async () => {
    const client = new FakeCompilerClient();
    const download = vi.fn();
    const slowText = deferred<string>();
    render(<App createClient={() => client} download={download} />);
    await initialize(client);
    const editor = screen.getByRole('textbox', { name: 'Model source' });

    chooseSourceFile(fileWithDeferredText('old.mdl', slowText));
    chooseSourceFile(new File(['record Latest {}'], 'latest.mdl'));
    await waitFor(() => {
      expect((editor as HTMLTextAreaElement).value).toBe(
        'record Latest {}',
      );
    });

    await act(async () => {
      slowText.resolve('record Old {}');
      await slowText.promise;
    });

    expect((editor as HTMLTextAreaElement).value).toBe(
      'record Latest {}',
    );
    expect(screen.queryByRole('alert')).toBeNull();
    fireEvent.click(
      screen.getByRole('button', { name: 'Export source' }),
    );
    expect(download).toHaveBeenCalledWith(
      'record Latest {}',
      'latest.mdl',
      'text/plain',
    );
  });

  test('an older import cannot change the latest clean snapshot', async () => {
    const client = new FakeCompilerClient();
    const confirmReplace = vi.fn(() => false);
    const slowText = deferred<string>();
    render(
      <App
        createClient={() => client}
        confirmReplace={confirmReplace}
      />,
    );
    await initialize(client);
    const editor = screen.getByRole('textbox', { name: 'Model source' });

    chooseSourceFile(fileWithDeferredText('old.mdl', slowText));
    chooseSourceFile(new File(['record Latest {}'], 'latest.mdl'));
    await waitFor(() => {
      expect((editor as HTMLTextAreaElement).value).toBe(
        'record Latest {}',
      );
    });
    await act(async () => {
      slowText.resolve('record Old {}');
      await slowText.promise;
    });

    fireEvent.change(editor, {
      target: { value: 'record Latest {}' },
    });
    chooseSourceFile(new File(['record Next {}'], 'next.mdl'));
    await waitFor(() => {
      expect((editor as HTMLTextAreaElement).value).toBe(
        'record Next {}',
      );
    });
    expect(confirmReplace).not.toHaveBeenCalled();
  });

  test('ignores an older import that rejects after the latest import', async () => {
    const client = new FakeCompilerClient();
    const download = vi.fn();
    const slowText = deferred<string>();
    render(<App createClient={() => client} download={download} />);
    await initialize(client);
    const editor = screen.getByRole('textbox', { name: 'Model source' });

    chooseSourceFile(fileWithDeferredText('old.mdl', slowText));
    chooseSourceFile(new File(['record Latest {}'], 'latest.mdl'));
    await waitFor(() => {
      expect((editor as HTMLTextAreaElement).value).toBe(
        'record Latest {}',
      );
    });

    await act(async () => {
      slowText.reject(new Error('late unreadable failure'));
      await expect(slowText.promise).rejects.toThrow(
        'late unreadable failure',
      );
    });

    expect((editor as HTMLTextAreaElement).value).toBe(
      'record Latest {}',
    );
    expect(screen.queryByRole('alert')).toBeNull();
    fireEvent.click(
      screen.getByRole('button', { name: 'Export source' }),
    );
    expect(download).toHaveBeenCalledWith(
      'record Latest {}',
      'latest.mdl',
      'text/plain',
    );
  });

  test('confirms before replacing changed source and respects cancellation', async () => {
    const client = new FakeCompilerClient();
    const confirmReplace = vi.fn(() => false);
    render(
      <App
        createClient={() => client}
        confirmReplace={confirmReplace}
      />,
    );
    await initialize(client);
    const editor = screen.getByRole('textbox', { name: 'Model source' });
    fireEvent.change(editor, {
      target: { value: 'record Unsaved {}' },
    });

    chooseSourceFile(
      new File(['record Imported {}'], 'imported.mdl'),
    );
    await waitFor(() => {
      expect(confirmReplace).toHaveBeenCalledOnce();
    });

    expect((editor as HTMLTextAreaElement).value).toBe(
      'record Unsaved {}',
    );
  });

  test('exports current source with a sanitized mdl filename', async () => {
    const client = new FakeCompilerClient();
    const download = vi.fn();
    render(<App createClient={() => client} download={download} />);
    await initialize(client);

    await importSource(
      new File(['record Imported {}'], 'Customer<>.txt'),
      'record Imported {}',
    );
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Model source' }),
      {
        target: { value: 'record Edited {}' },
      },
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Export source' }),
    );

    expect(download).toHaveBeenCalledWith(
      'record Edited {}',
      'Customer.mdl',
      'text/plain',
    );
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

    fireEvent.click(
      screen.getByRole('button', { name: 'Generate JSON Schema' }),
    );
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
    fireEvent.click(
      screen.getByRole('button', { name: 'Generate JSON Schema' }),
    );
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
    expect(
      screen.getByText('Stale—source changed after generation'),
    ).toBeTruthy();
  });

  test('renders generated artifacts in compiler order', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    await generateArtifacts(client, [
      {
        path: 'z-last.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Z"}',
        source_refs: ['file:///main.mdl'],
      },
      {
        path: 'a-first.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"A"}',
        source_refs: ['file:///main.mdl'],
      },
    ]);

    const options = screen
      .getByRole('combobox', { name: 'Artifact' })
      .querySelectorAll('option');
    expect([...options].map((option) => option.textContent)).toEqual([
      'z-last.schema.json',
      'a-first.schema.json',
    ]);
  });

  test('selecting an artifact updates the preview', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    await generateArtifacts(client, [
      {
        path: 'customer.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Customer"}',
        source_refs: ['file:///main.mdl'],
      },
      {
        path: 'order.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Order"}',
        source_refs: ['file:///main.mdl'],
      },
    ]);
    fireEvent.change(screen.getByRole('combobox', { name: 'Artifact' }), {
      target: { value: 'order.schema.json' },
    });

    expect(screen.getByLabelText('Artifact output').textContent).toBe(
      '{"title":"Order"}',
    );
  });

  test('exports only the selected artifact with a json filename', async () => {
    const client = new FakeCompilerClient();
    const download = vi.fn();
    render(<App createClient={() => client} download={download} />);
    await initialize(client);

    await generateArtifacts(client, [
      {
        path: 'customer.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Customer"}',
        source_refs: ['file:///main.mdl'],
      },
      {
        path: '../Order<>.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Order"}',
        source_refs: ['file:///main.mdl'],
      },
    ]);
    fireEvent.change(screen.getByRole('combobox', { name: 'Artifact' }), {
      target: { value: '../Order<>.schema.json' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Export artifact' }),
    );

    expect(download).toHaveBeenCalledWith(
      '{"title":"Order"}',
      'Order-.schema.json',
      'application/schema+json',
    );
  });

  test('disables artifact export before successful generation', () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);

    expect(
      (
        screen.getByRole('button', {
          name: 'Export artifact',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
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

  test('recovers with retained editor state after a BFCache restoration', async () => {
    const firstClient = new FakeCompilerClient();
    const secondClient = new FakeCompilerClient();
    const createClient = vi
      .fn()
      .mockReturnValueOnce(firstClient)
      .mockReturnValueOnce(secondClient);
    const { unmount } = render(<App createClient={createClient} />);
    await initialize(firstClient);

    fireEvent.click(
      screen.getByRole('button', { name: 'Generate JSON Schema' }),
    );
    const generation = latestRequest(firstClient.compileRequests);
    await act(async () => {
      generation.resolve({
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
      await generation.promise;
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Model source' }), {
      target: { value: 'record Restored {}' },
    });

    const pagehide = new Event('pagehide');
    Object.defineProperty(pagehide, 'persisted', { value: true });
    const pageshow = new Event('pageshow');
    Object.defineProperty(pageshow, 'persisted', { value: true });
    act(() => {
      window.dispatchEvent(pagehide);
      window.dispatchEvent(pageshow);
      window.dispatchEvent(pageshow);
    });

    expect(firstClient.dispose).toHaveBeenCalledTimes(1);
    expect(createClient).toHaveBeenCalledTimes(2);
    expect(
      (screen.getByRole('button', { name: 'Validate' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole('textbox', {
          name: 'Model source',
        }) as HTMLTextAreaElement
      ).value,
    ).toBe('record Restored {}');
    expect(screen.getByLabelText('Artifact output').textContent).toBe(
      '{"title":"Customer"}',
    );
    expect(
      screen.getByText('Stale—source changed after generation'),
    ).toBeTruthy();

    await initialize(secondClient);
    expect(
      (screen.getByRole('button', { name: 'Validate' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);

    unmount();
    expect(firstClient.dispose).toHaveBeenCalledTimes(1);
    expect(secondClient.dispose).toHaveBeenCalledTimes(1);
    window.dispatchEvent(pageshow);
    expect(createClient).toHaveBeenCalledTimes(2);
  });

  test('routes the skip link target to the source editor focus handle', () => {
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
    expect(sourceEditorSpies.focus).toHaveBeenCalledTimes(1);
  });
});
