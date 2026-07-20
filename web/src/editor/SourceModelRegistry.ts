import type { editor } from 'monaco-editor';

import type { PlaygroundFile } from '../workspace';

export interface SourceModelRegistry {
  reconcile(files: PlaygroundFile[]): void;
  model(path: string): editor.ITextModel | undefined;
  paths(): string[];
  isApplyingExternalChange(): boolean;
  dispose(): void;
}

export interface SourceModelApi {
  createModel(content: string, uri: string): editor.ITextModel;
}

interface RegisteredModel {
  model: editor.ITextModel;
  version: number;
}

export function createSourceModelRegistry(
  api: SourceModelApi,
): SourceModelRegistry {
  const models = new Map<string, RegisteredModel>();
  let applyingExternalChange = false;

  return {
    reconcile(files) {
      const incomingPaths = new Set(files.map((file) => file.path));
      for (const [path, registered] of models) {
        if (!incomingPaths.has(path)) {
          registered.model.dispose();
          models.delete(path);
        }
      }

      for (const file of [...files].sort((left, right) =>
        left.path.localeCompare(right.path),
      )) {
        const registered = models.get(file.path);
        if (registered === undefined) {
          models.set(file.path, {
            model: api.createModel(file.content, sourceUri(file.path)),
            version: file.version,
          });
          continue;
        }
        if (registered.version === file.version) {
          continue;
        }
        registered.version = file.version;
        if (registered.model.getValue() !== file.content) {
          applyingExternalChange = true;
          try {
            registered.model.setValue(file.content);
          } finally {
            applyingExternalChange = false;
          }
        }
      }
    },
    model(path) {
      return models.get(path)?.model;
    },
    paths() {
      return [...models.keys()].sort((left, right) =>
        left.localeCompare(right),
      );
    },
    isApplyingExternalChange() {
      return applyingExternalChange;
    },
    dispose() {
      for (const registered of models.values()) {
        registered.model.dispose();
      }
      models.clear();
    },
  };
}

function sourceUri(path: string): string {
  return `file:///${path.split('/').map(encodeURIComponent).join('/')}`;
}
