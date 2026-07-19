import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';

type MonacoScope = typeof globalThis & {
  MonacoEnvironment?: {
    getWorker(moduleId: string, label: string): Worker;
  };
};

(globalThis as MonacoScope).MonacoEnvironment = {
  getWorker(_moduleId, label) {
    return label === 'json' ? new jsonWorker() : new editorWorker();
  },
};
