import { describe, expect, test } from 'vitest';

import type { BrowserGraphEdge, BrowserGraphNode } from '../protocol';
import type { LayoutRequest } from './graph-types';
import {
  applyLayout,
  buildElkGraph,
  layoutDirection,
  nodeSize,
} from './layout-model';

function graphNode(
  id: string,
  kind: string,
  overrides: Partial<BrowserGraphNode> = {},
): BrowserGraphNode {
  return {
    id,
    kind,
    label: id,
    metadata: {},
    source_range: null,
    ...overrides,
  };
}

function graphEdge(
  source: string,
  target: string,
  kind = 'contains',
): BrowserGraphEdge {
  return {
    id: `${kind}:${source}->${target}`,
    source,
    target,
    kind,
    label: null,
    metadata: {},
  };
}

function request(overrides: Partial<LayoutRequest> = {}): LayoutRequest {
  return {
    id: 'request-1',
    mode: 'domain',
    nodes: [graphNode('domain:sales', 'domain'), graphNode('model:sales.Order', 'entity')],
    edges: [graphEdge('domain:sales', 'model:sales.Order')],
    ...overrides,
  };
}

describe('nodeSize', () => {
  test('gives fields and versions their own heights', () => {
    expect(nodeSize('field').height).toBe(28);
    expect(nodeSize('version').height).toBe(32);
    expect(nodeSize('entity').height).toBe(40);
    expect(nodeSize('unknown-kind').height).toBe(40);
  });
});

describe('layoutDirection', () => {
  test('lays entity mode out downwards and everything else rightwards', () => {
    expect(layoutDirection('entity')).toBe('DOWN');
    expect(layoutDirection('domain')).toBe('RIGHT');
    expect(layoutDirection('projection')).toBe('RIGHT');
    expect(layoutDirection('lineage')).toBe('RIGHT');
  });
});

describe('buildElkGraph', () => {
  test('sizes every node and forwards each edge', () => {
    const graph = buildElkGraph(request());
    expect(graph.children).toEqual([
      { id: 'domain:sales', width: 180, height: 40 },
      { id: 'model:sales.Order', width: 180, height: 40 },
    ]);
    expect(graph.edges).toEqual([
      {
        id: 'contains:domain:sales->model:sales.Order',
        sources: ['domain:sales'],
        targets: ['model:sales.Order'],
      },
    ]);
  });

  test('takes the layout direction from the mode', () => {
    expect(buildElkGraph(request()).layoutOptions['elk.direction']).toBe(
      'RIGHT',
    );
    expect(
      buildElkGraph(request({ mode: 'entity' })).layoutOptions['elk.direction'],
    ).toBe('DOWN');
  });
});

describe('applyLayout', () => {
  test('places nodes at their laid out positions', () => {
    const positions = new Map([['domain:sales', { x: 20, y: 40 }]]);
    const { nodes } = applyLayout(request(), positions);
    expect(nodes[0]?.position).toEqual({ x: 20, y: 40 });
    expect(nodes[0]?.type).toBe('domain');
    expect(nodes[0]?.width).toBe(180);
  });

  test('falls back to the origin for nodes ELK did not return', () => {
    const { nodes } = applyLayout(request(), new Map());
    expect(nodes[1]?.position).toEqual({ x: 0, y: 0 });
  });

  test('records the layout direction so handles match the flow', () => {
    const rightwards = applyLayout(request(), new Map());
    expect(rightwards.nodes[0]?.data.direction).toBe('RIGHT');
    const downwards = applyLayout(request({ mode: 'entity' }), new Map());
    expect(downwards.nodes[0]?.data.direction).toBe('DOWN');
  });

  test('maps edges onto their kind-specific edge type', () => {
    const { edges } = applyLayout(
      request({ edges: [graphEdge('a', 'b', 'projects')] }),
      new Map(),
    );
    expect(edges[0]?.type).toBe('projects');
    expect(edges[0]?.data).toEqual({ kind: 'projects', label: null });
  });

  test('carries the request id through so stale layouts can be discarded', () => {
    expect(applyLayout(request(), new Map()).id).toBe('request-1');
  });
});
