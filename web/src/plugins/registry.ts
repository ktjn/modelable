import type { ComponentType } from 'react';

import type { BrowserArtifact } from '../protocol';

export const PLAYGROUND_PLUGIN_API_VERSION = 1;

export interface ArtifactViewerProps {
  artifact: BrowserArtifact;
  isStale: boolean;
}

export interface ArtifactViewerDefinition {
  readonly id: string;
  readonly label: string;
  readonly extensions: readonly string[];
  readonly component: ComponentType<ArtifactViewerProps>;
}

export interface PlaygroundPlugin {
  readonly apiVersion: typeof PLAYGROUND_PLUGIN_API_VERSION;
  readonly id: string;
  readonly name: string;
  readonly version: string;
  readonly artifactViewers?: readonly ArtifactViewerDefinition[];
}

export interface PlaygroundPluginRegistry {
  readonly plugins: readonly PlaygroundPlugin[];
  findArtifactViewer(artifact: BrowserArtifact): ArtifactViewerDefinition | null;
}

export function createPlaygroundPluginRegistry(
  plugins: readonly PlaygroundPlugin[] = [],
): PlaygroundPluginRegistry {
  const artifactViewers: ArtifactViewerDefinition[] = [];
  const pluginIds = new Set<string>();
  const viewerIds = new Set<string>();

  for (const plugin of plugins) {
    validatePlugin(plugin);
    if (pluginIds.has(plugin.id)) {
      throw new Error(`Duplicate Playground plugin id: ${plugin.id}`);
    }
    pluginIds.add(plugin.id);

    for (const viewer of plugin.artifactViewers ?? []) {
      validateArtifactViewer(plugin, viewer);
      if (viewerIds.has(viewer.id)) {
        throw new Error(`Duplicate artifact viewer id: ${viewer.id}`);
      }
      viewerIds.add(viewer.id);
      artifactViewers.push(viewer);
    }
  }

  return {
    plugins: [...plugins],
    findArtifactViewer(artifact) {
      const extension = artifact.path.slice(artifact.path.lastIndexOf('.')).toLowerCase();
      return artifactViewers.find((viewer) => viewer.extensions.includes(extension)) ?? null;
    },
  };
}

function validatePlugin(plugin: PlaygroundPlugin): void {
  if (plugin.apiVersion !== PLAYGROUND_PLUGIN_API_VERSION) {
    throw new Error(
      `Unsupported Playground plugin API version for ${plugin.id}: ${plugin.apiVersion}`,
    );
  }
  if (!isNonEmptyString(plugin.id) || !isNonEmptyString(plugin.name)) {
    throw new Error('Playground plugins require non-empty id and name values');
  }
  if (!isNonEmptyString(plugin.version)) {
    throw new Error(`Playground plugin ${plugin.id} requires a version`);
  }
}

function validateArtifactViewer(
  plugin: PlaygroundPlugin,
  viewer: ArtifactViewerDefinition,
): void {
  if (!isNonEmptyString(viewer.id) || !isNonEmptyString(viewer.label)) {
    throw new Error(`Artifact viewers from ${plugin.id} require id and label values`);
  }
  if (
    viewer.extensions.length === 0 ||
    viewer.extensions.some(
      (extension) => !/^\.[a-z0-9][a-z0-9.-]*$/.test(extension.toLowerCase()),
    )
  ) {
    throw new Error(`Artifact viewer ${viewer.id} requires valid file extensions`);
  }
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}
