import { ArtifactEditor } from '../editor/ArtifactEditor';
import type { BrowserArtifact } from '../protocol';
import type { PlaygroundPluginRegistry } from '../plugins/registry';

export interface OutputPanelProps {
  artifacts: BrowserArtifact[];
  selectedArtifactPath: string | null;
  isStale: boolean;
  disabled: boolean;
  onSelect(path: string): void;
  onDownload(path: string): void;
  onDownloadAll(): void;
  pluginRegistry?: PlaygroundPluginRegistry;
}

export function OutputPanel({
  artifacts,
  selectedArtifactPath,
  isStale,
  disabled,
  onSelect,
  onDownload,
  onDownloadAll,
  pluginRegistry,
}: OutputPanelProps) {
  const selectedArtifact =
    artifacts.find((artifact) => artifact.path === selectedArtifactPath) ??
    artifacts[0] ??
    null;

  if (artifacts.length === 0) {
    return (
      <section className="output-panel" aria-label="Generated output">
        <div className="output-panel__empty">
          <p>No artifact yet</p>
          <p>Pick a target language and press Generate.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="output-panel" aria-label="Generated output">
      <div className="output-panel__list">
        <div className="output-panel__list-header">
          <span className="output-panel__list-title">Artifacts</span>
          {isStale ? (
            <span className="output-panel__stale-label">Stale—source changed after generation</span>
          ) : (
            <span className="output-panel__fresh-label">Current</span>
          )}
        </div>
        <button
          type="button"
          className="output-panel__download-all"
          disabled={disabled}
          onClick={onDownloadAll}
        >
          Download all
        </button>
        <ul role="list" aria-label="Generated artifacts">
          {artifacts.map((artifact) => (
            <li
              key={artifact.path}
              className={`output-panel__item${
                artifact.path === selectedArtifactPath
                  ? ' output-panel__item--active'
                  : ''
              }`}
              aria-current={artifact.path === selectedArtifactPath}
            >
              <button
                type="button"
                className="output-panel__item-select"
                aria-label={artifact.path}
                onClick={() => onSelect(artifact.path)}
              >
                <span className="output-panel__item-name">{artifact.path}</span>
              </button>
              <button
                type="button"
                className="output-panel__item-download"
                aria-label={`Download ${artifact.path}`}
                title={`Download ${artifact.path}`}
                onClick={() => onDownload(artifact.path)}
              >
                ↓
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="output-panel__editor">
        {selectedArtifact === null ? (
          <p className="output-panel__empty">Select an artifact to preview</p>
        ) : (
          <ArtifactPreview
            artifact={selectedArtifact}
            isStale={isStale}
            pluginRegistry={pluginRegistry}
          />
        )}
      </div>
    </section>
  );
}

function ArtifactPreview({
  artifact,
  isStale,
  pluginRegistry,
}: {
  artifact: BrowserArtifact;
  isStale: boolean;
  pluginRegistry?: PlaygroundPluginRegistry;
}) {
  const viewer = pluginRegistry?.findArtifactViewer(artifact) ?? null;
  if (viewer === null) {
    return <ArtifactEditor value={artifact.content} />;
  }
  const Viewer = viewer.component;
  return <Viewer artifact={artifact} isStale={isStale} />;
}
