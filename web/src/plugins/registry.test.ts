import { describe, expect, test } from 'vitest';

import type { BrowserArtifact } from '../protocol';
import {
  createPlaygroundPluginRegistry,
  PLAYGROUND_PLUGIN_API_VERSION,
  type ArtifactViewerProps,
} from './registry';

const artifact: BrowserArtifact = {
  path: 'generated/example.graphql',
  content: 'type Example { id: ID! }',
  media_type: 'text/plain',
  source_refs: [],
};

function Viewer(_props: ArtifactViewerProps) {
  return null;
}

function plugin(overrides: Record<string, unknown> = {}) {
  return {
    apiVersion: PLAYGROUND_PLUGIN_API_VERSION,
    id: 'graphql-tools',
    name: 'GraphQL tools',
    version: '1.0.0',
    artifactViewers: [
      {
        id: 'graphql',
        label: 'GraphQL preview',
        extensions: ['.graphql'],
        component: Viewer,
      },
    ],
    ...overrides,
  } as const;
}

describe('Playground plugin registry', () => {
  test('resolves an explicitly registered artifact viewer by extension', () => {
    const registry = createPlaygroundPluginRegistry([plugin()]);

    expect(registry.plugins).toHaveLength(1);
    expect(registry.findArtifactViewer(artifact)?.id).toBe('graphql');
    expect(registry.findArtifactViewer({ ...artifact, path: 'model.json' })).toBeNull();
  });

  test('rejects duplicate plugin and viewer identities', () => {
    expect(() => createPlaygroundPluginRegistry([plugin(), plugin()])).toThrow(
      'Duplicate Playground plugin id',
    );
    expect(() =>
      createPlaygroundPluginRegistry([
        plugin({ id: 'first' }),
        plugin({ id: 'second' }),
      ]),
    ).toThrow('Duplicate artifact viewer id');
  });

  test('rejects unsupported API versions and invalid extensions', () => {
    expect(() =>
      createPlaygroundPluginRegistry([plugin({ apiVersion: 2 })]),
    ).toThrow('Unsupported Playground plugin API version');
    expect(() =>
      createPlaygroundPluginRegistry([
        plugin({
          artifactViewers: [
            {
              id: 'invalid',
              label: 'Invalid',
              extensions: ['graphql'],
              component: Viewer,
            },
          ],
        }),
      ]),
    ).toThrow('requires valid file extensions');
  });
});
