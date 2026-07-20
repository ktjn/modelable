import type { editor } from 'monaco-editor';
import { expect, test } from 'vitest';

import {
  createSourceModelRegistry,
  type SourceModelApi,
} from './SourceModelRegistry';

test('reconciles models without recreating unaffected files', () => {
  const api = fakeMonacoModelApi();
  const registry = createSourceModelRegistry(api);
  registry.reconcile([
    { path: 'a.mdl', content: 'domain a {}', version: 1 },
    { path: 'b.mdl', content: 'domain b {}', version: 1 },
  ]);
  const firstA = registry.model('a.mdl');

  registry.reconcile([
    { path: 'a.mdl', content: 'domain a {}', version: 1 },
    { path: 'c.mdl', content: 'domain b {}', version: 2 },
  ]);

  expect(registry.model('a.mdl')).toBe(firstA);
  expect(api.model('b.mdl')?.disposed).toBe(true);
  expect(registry.paths()).toEqual(['a.mdl', 'c.mdl']);
});

test('updates external content without reporting it as a user edit', () => {
  const api = fakeMonacoModelApi();
  const registry = createSourceModelRegistry(api);
  registry.reconcile([
    { path: 'main.mdl', content: 'domain old {}', version: 1 },
  ]);
  registry.reconcile([
    { path: 'main.mdl', content: 'domain formatted {}', version: 2 },
  ]);
  expect(registry.model('main.mdl')?.getValue()).toBe(
    'domain formatted {}',
  );
});

interface FakeModel {
  disposed: boolean;
  getValue(): string;
  setValue(value: string): void;
  dispose(): void;
}

function fakeMonacoModelApi(): SourceModelApi & {
  model(path: string): FakeModel | undefined;
} {
  const models = new Map<string, FakeModel>();
  return {
    createModel(content, uri) {
      let value = content;
      const model: FakeModel = {
        disposed: false,
        getValue: () => value,
        setValue(next) {
          value = next;
        },
        dispose() {
          this.disposed = true;
        },
      };
      models.set(decodeURIComponent(uri.slice('file:///'.length)), model);
      return model as unknown as editor.ITextModel;
    },
    model(path) {
      return models.get(path);
    },
  };
}
