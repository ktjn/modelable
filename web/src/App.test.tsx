// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { IDBFactory } from 'fake-indexeddb';
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  vi,
} from 'vitest';

import indexHtml from '../index.html?raw';
import { App } from './App';
import { BrowserCompilerError } from './client';
import type {
  BrowserCompileResult,
  BrowserCompletionResult,
  BrowserFormatResult,
  BrowserHoverResult,
  BrowserLanguagePosition,
  BrowserSource,
  BrowserWorkspaceResult,
} from './protocol';
import type { PlaygroundWorkspace } from './workspace';
import type { WorkspaceRepository } from './workspace-repository';
import type {
  WorkspaceLoadResult,
  WorkspaceSaveResult,
} from './workspace-repository';

const sourceEditorSpies = vi.hoisted(() => ({
  applyFormattedText: vi.fn(),
  focus: vi.fn(),
}));

vi.mock('./editor/SourceEditor', async () => {
  const {
    forwardRef,
    useImperativeHandle,
    useRef,
  } = await import('react');
  return {
    SourceEditor: forwardRef(function FakeSourceEditor(
      {
        files,
        activeFile,
        onContentChange,
      }: {
        files: PlaygroundWorkspace['files'];
        activeFile: string;
        onContentChange(path: string, content: string): void;
      },
      ref,
    ) {
      const propsRef = useRef({ files, activeFile, onContentChange });
      propsRef.current = { files, activeFile, onContentChange };
      const active = files.find((file) => file.path === activeFile);
      useImperativeHandle(ref, () => ({
        getSource(): BrowserSource {
          const current = propsRef.current;
          const file = current.files.find(
            (candidate) => candidate.path === current.activeFile,
          );
          return {
            uri: `file:///${current.activeFile}`,
            text: file?.content ?? '',
            version: file?.version ?? 1,
          };
        },
        applyFormattedText(path: string, text: string) {
          sourceEditorSpies.applyFormattedText(path, text);
          propsRef.current.onContentChange(path, text);
        },
        replaceText(text: string) {
          const current = propsRef.current;
          current.onContentChange(current.activeFile, text);
        },
        focus() {
          sourceEditorSpies.focus();
        },
      }));

      return (
        <textarea
          aria-label="Model source"
          value={active?.content ?? ''}
          onChange={(event) => {
            onContentChange(activeFile, event.target.value);
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
  readonly openWorkspace = vi.fn(
    (_workspaceRevision: number, _sources: BrowserSource[]) => {
    const request = deferred<BrowserWorkspaceResult>();
    this.workspaceRequests.push(request);
    return request.promise;
    },
  );
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
  readonly completion = vi.fn(
    async (
      _position: BrowserLanguagePosition,
    ): Promise<BrowserCompletionResult> => ({ items: [] }),
  );
  readonly hover = vi.fn(
    async (
      _position: BrowserLanguagePosition,
    ): Promise<BrowserHoverResult> => ({ hover: null }),
  );
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
  await waitFor(() => {
    expect(screen.queryByText(/restoring local workspace/i)).toBeNull();
  });
  await waitFor(() => {
    expect(client.openWorkspace).toHaveBeenCalledTimes(1);
  });
}

function chooseWorkspaceFiles(files: File[]): void {
  const input = screen.getByLabelText<HTMLInputElement>(
    'Import workspace files',
  );
  fireEvent.change(input, { target: { files } });
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

beforeEach(() => {
  Object.defineProperty(globalThis, 'indexedDB', {
    configurable: true,
    value: new IDBFactory(),
  });
});

describe('App', () => {
  test('validation and generation send every file in path order', async () => {
    const client = new FakeCompilerClient();
    const workspace: PlaygroundWorkspace = {
      schemaVersion: 1,
      id: 'local',
      revision: 3,
      activeFile: 'a.mdl',
      files: [
        { path: 'z.mdl', content: 'domain z {}', version: 1 },
        { path: 'a.mdl', content: 'domain a {}', version: 2 },
      ],
    };
    const repository: WorkspaceRepository = {
      load: vi.fn(async (): Promise<WorkspaceLoadResult> => ({
        status: 'ready',
        workspace,
      })),
      save: vi.fn(
        async (): Promise<WorkspaceSaveResult> => 'saved',
      ),
      remove: vi.fn(async () => undefined),
    };
    render(
      <App
        createClient={() => client}
        createRepository={() => repository}
      />,
    );
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    expect(client.openWorkspace).toHaveBeenLastCalledWith(
      3,
      [
        { uri: 'file:///a.mdl', text: 'domain a {}', version: 2 },
        { uri: 'file:///z.mdl', text: 'domain z {}', version: 1 },
      ],
    );
    await act(async () => {
      const request = latestRequest(client.workspaceRequests);
      request.resolve({
        workspace_revision: 3,
        diagnostics: [],
        source_hashes: {},
      });
      await request.promise;
    });

    fireEvent.click(
      screen.getByRole('button', { name: 'Generate JSON Schema' }),
    );
    expect(client.compileJsonSchema).toHaveBeenLastCalledWith(
      client.openWorkspace.mock.calls.at(-1)?.[1],
    );
  });

  test('disables actions during initialization and enables them after success', async () => {
    const client = new FakeCompilerClient();
    const now = vi
      .fn<() => number>()
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(350);
    render(<App createClient={() => client} now={now} />);

    expect(screen.getByText(/restoring local workspace/i)).toBeTruthy();

    await initialize(client);

    for (const name of ['Validate', 'Format', 'Generate JSON Schema']) {
      expect(
        (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
      ).toBe(false);
    }
    expect(screen.getByRole('status').textContent).toMatch(/compiler ready/i);
    expect(
      screen.getByTestId('metrics').getAttribute(
        'data-initialization-duration-ms',
      ),
    ).toBe('250');
  });

  test('disables duplicate actions while one request is pending', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));

    expect(client.openWorkspace).toHaveBeenCalledTimes(2);
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
    expect(client.openWorkspace).toHaveBeenCalledTimes(2);
    await act(async () => {
      const request = latestRequest(client.workspaceRequests);
      request.resolve({
        workspace_revision: 1,
        diagnostics: [],
        source_hashes: {},
      });
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
    expect(client.openWorkspace).toHaveBeenCalledTimes(2);

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

  test('exposes visible toolbar names and command shortcuts', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

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
        workspace_revision: 1,
        diagnostics: [documentDiagnostic],
        source_hashes: {},
      });
      await request.promise;
    });

    expect(screen.getByText('Customer is invalid')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toMatch(/1 diagnostic/i);
  });

  test('exports the active source with its mdl filename', async () => {
    const client = new FakeCompilerClient();
    const download = vi.fn();
    render(<App createClient={() => client} download={download} />);
    await initialize(client);

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
      'main.mdl',
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
        workspace_revision: 1,
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
      'main.mdl',
      'record Customer {\n}\n',
    );
  });

  test('creates, selects, and deletes workspace files with confirmation', async () => {
    const client = new FakeCompilerClient();
    const confirmReplace = vi.fn(() => false);
    render(
      <App
        createClient={() => client}
        confirmReplace={confirmReplace}
      />,
    );
    await initialize(client);

    fireEvent.change(
      screen.getByRole('textbox', { name: 'Workspace file path' }),
      { target: { value: 'customer.mdl' } },
    );
    fireEvent.click(screen.getByRole('button', { name: 'New file' }));

    expect(
      screen.getByRole('button', { name: 'customer.mdl' }).getAttribute(
        'aria-current',
      ),
    ).toBe('true');
    expect(
      (
        screen.getByRole('textbox', {
          name: 'Model source',
        }) as HTMLTextAreaElement
      ).value,
    ).toBe('');

    fireEvent.click(screen.getByRole('button', { name: 'main.mdl' }));
    expect(
      screen.getByRole('button', { name: 'main.mdl' }).getAttribute(
        'aria-current',
      ),
    ).toBe('true');

    fireEvent.click(
      screen.getByRole('button', { name: 'Delete active' }),
    );
    expect(confirmReplace).toHaveBeenCalledWith(
      'Delete workspace file main.mdl?',
    );
    expect(screen.getByRole('button', { name: 'main.mdl' })).toBeTruthy();

    confirmReplace.mockReturnValue(true);
    fireEvent.click(
      screen.getByRole('button', { name: 'Delete active' }),
    );
    expect(
      screen.queryByRole('button', { name: 'main.mdl' }),
    ).toBeNull();
  });

  test('imports multiple files atomically and confirms each replacement', async () => {
    const client = new FakeCompilerClient();
    const confirmReplace = vi.fn(
      (message: string) => !message.includes('main.mdl'),
    );
    render(
      <App
        createClient={() => client}
        confirmReplace={confirmReplace}
      />,
    );
    await initialize(client);
    const originalSource = (
      screen.getByRole('textbox', {
        name: 'Model source',
      }) as HTMLTextAreaElement
    ).value;

    chooseWorkspaceFiles([
      new File(['domain replacement {}'], 'main.mdl'),
      new File(['domain customer {}'], 'customer.mdl'),
    ]);

    expect(
      await screen.findByRole('button', { name: 'customer.mdl' }),
    ).toBeTruthy();
    expect(confirmReplace).toHaveBeenCalledWith(
      'Replace existing workspace file main.mdl?',
    );
    fireEvent.click(screen.getByRole('button', { name: 'main.mdl' }));
    expect(
      (
        screen.getByRole('textbox', {
          name: 'Model source',
        }) as HTMLTextAreaElement
      ).value,
    ).toBe(originalSource);
  });

  test('keeps the playground usable when local storage is unavailable', async () => {
    const client = new FakeCompilerClient();
    const repository: WorkspaceRepository = {
      load: vi.fn(async () => {
        throw new Error('storage unavailable');
      }),
      save: vi.fn(async () => {
        throw new Error('storage unavailable');
      }),
      remove: vi.fn(async () => undefined),
    };
    render(
      <App
        createClient={() => client}
        createRepository={() => repository}
      />,
    );
    await initialize(client);

    expect(screen.getByText(/storage unavailable/i)).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Validate' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    expect(
      screen.getByRole('button', { name: 'Retry storage' }),
    ).toBeTruthy();
  });

  test('exports and explicitly resets incompatible stored state', async () => {
    const client = new FakeCompilerClient();
    const raw = { schemaVersion: 99, source: '<script>secret</script>' };
    const repository: WorkspaceRepository = {
      load: vi.fn(async (): Promise<WorkspaceLoadResult> => ({
        status: 'recovery-required',
        reason: 'incompatible',
        raw,
      })),
      save: vi.fn(
        async (): Promise<WorkspaceSaveResult> => 'saved',
      ),
      remove: vi.fn(async () => undefined),
    };
    const download = vi.fn();
    render(
      <App
        createClient={() => client}
        createRepository={() => repository}
        download={download}
      />,
    );

    expect(
      await screen.findByText('Stored workspace needs recovery'),
    ).toBeTruthy();
    expect(document.body.textContent).not.toContain('secret');
    fireEvent.click(
      screen.getByRole('button', { name: 'Export recovery data' }),
    );
    expect(download).toHaveBeenCalledWith(
      JSON.stringify(raw, null, 2),
      'modelable-playground-recovery.json',
      'application/json',
    );

    fireEvent.click(
      screen.getByRole('button', { name: 'Reset local workspace' }),
    );
    expect(
      await screen.findByRole('button', { name: 'main.mdl' }),
    ).toBeTruthy();
    expect(repository.remove).toHaveBeenCalledWith('local');
  });

  test('ignores formatted text after the active file is edited', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

    fireEvent.click(screen.getByRole('button', { name: 'Format' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Model source' }), {
      target: { value: 'record EditedWhileFormatting {}' },
    });
    const request = latestRequest(client.formatRequests);
    await act(async () => {
      request.resolve({
        diagnostics: [],
        replacement_text: 'record StaleFormat {}',
      });
      await request.promise;
    });

    expect(sourceEditorSpies.applyFormattedText).not.toHaveBeenCalled();
    expect(
      (
        screen.getByRole('textbox', {
          name: 'Model source',
        }) as HTMLTextAreaElement
      ).value,
    ).toBe('record EditedWhileFormatting {}');
  });

  test('clears artifacts after a workspace edit before failed generation', async () => {
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

    expect(screen.getByLabelText('Artifact output').textContent).toBe('');
    expect(screen.getByText('No artifact yet')).toBeTruthy();
  });

  test('marks current artifacts stale for error diagnostics and restores current status after regeneration', async () => {
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
      '{"title":"Order"}',
    );
    expect(
      (
        screen.getByRole('combobox', {
          name: 'Artifact',
        }) as HTMLSelectElement
      ).value,
    ).toBe('order.schema.json');
    expect(
      screen.getByText('Stale—source changed after generation'),
    ).toBeTruthy();

    await generateArtifacts(client, [
      {
        path: 'customer.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Regenerated"}',
        source_refs: ['file:///main.mdl'],
      },
    ]);
    expect(screen.getByText('Current')).toBeTruthy();
  });

  test('marks current artifacts stale for a recoverable generation error and restores current status after regeneration', async () => {
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

    fireEvent.click(
      screen.getByRole('button', { name: 'Generate JSON Schema' }),
    );
    const failedRequest = latestRequest(client.compileRequests);
    await act(async () => {
      failedRequest.reject(
        new BrowserCompilerError(
          'INVALID_REQUEST',
          'Generation request failed',
        ),
      );
      await expect(failedRequest.promise).rejects.toThrow(
        'Generation request failed',
      );
    });

    expect(screen.getByLabelText('Artifact output').textContent).toBe(
      '{"title":"Order"}',
    );
    expect(
      (
        screen.getByRole('combobox', {
          name: 'Artifact',
        }) as HTMLSelectElement
      ).value,
    ).toBe('order.schema.json');
    expect(
      screen.getByText('Stale—source changed after generation'),
    ).toBeTruthy();

    await generateArtifacts(client, [
      {
        path: 'customer.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Regenerated"}',
        source_refs: ['file:///main.mdl'],
      },
    ]);
    expect(screen.getByText('Current')).toBeTruthy();
  });

  test('marks current artifacts stale for an operation-time compiler failure and restores current status after retry', async () => {
    const firstClient = new FakeCompilerClient();
    const secondClient = new FakeCompilerClient();
    const createClient = vi
      .fn()
      .mockReturnValueOnce(firstClient)
      .mockReturnValueOnce(secondClient);
    render(<App createClient={createClient} />);
    await initialize(firstClient);
    await generateArtifacts(firstClient, [
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

    fireEvent.click(
      screen.getByRole('button', { name: 'Generate JSON Schema' }),
    );
    const failedRequest = latestRequest(firstClient.compileRequests);
    await act(async () => {
      failedRequest.reject(
        new BrowserCompilerError(
          'COMPILER_FAILED',
          'Compiler worker failed',
        ),
      );
      await expect(failedRequest.promise).rejects.toThrow(
        'Compiler worker failed',
      );
    });

    expect(screen.getByLabelText('Artifact output').textContent).toBe(
      '{"title":"Order"}',
    );
    expect(
      (
        screen.getByRole('combobox', {
          name: 'Artifact',
        }) as HTMLSelectElement
      ).value,
    ).toBe('order.schema.json');
    expect(
      screen.getByText('Stale—source changed after generation'),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Retry compiler' }));
    await initialize(secondClient);
    await generateArtifacts(secondClient, [
      {
        path: 'customer.schema.json',
        media_type: 'application/schema+json',
        content: '{"title":"Regenerated"}',
        source_refs: ['file:///main.mdl'],
      },
    ]);
    expect(screen.getByText('Current')).toBeTruthy();
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

  test('disables artifact export before successful generation', async () => {
    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);
    await initialize(client);

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
    await waitFor(() => {
      expect(screen.queryByText(/restoring local workspace/i)).toBeNull();
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
    expect(screen.getByLabelText('Artifact output').textContent).toBe('');
    expect(screen.getByText('No artifact yet')).toBeTruthy();

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

  test('routes the skip link target to the source editor focus handle', async () => {
    const client = new FakeCompilerClient();
    const template = document.createElement('template');
    template.innerHTML = indexHtml;
    const skipLink =
      template.content.querySelector<HTMLAnchorElement>('.skip-link');

    render(<App createClient={() => client} />);
    await initialize(client);

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
