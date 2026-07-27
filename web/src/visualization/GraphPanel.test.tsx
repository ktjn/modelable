// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import type { BrowserGraphResult } from '../protocol';
import type { GraphNode } from './graph-types';
import { GraphPanel, type GraphPanelProps } from './GraphPanel';

const mocks = vi.hoisted(() => ({
  useGraphExport: vi.fn(() => ({
    exportSvg: vi.fn(),
    exportPng: vi.fn(),
  })),
  viewport: {
    fitViewOptions: {
      minZoom: 0.6,
      maxZoom: 1,
      padding: 0.1,
    },
    showMiniMap: false,
    onMoveStart: vi.fn(),
    onFitView: vi.fn(),
  },
}));

const node: GraphNode = {
  id: 'domain:sales',
  type: 'domain',
  position: { x: 0, y: 0 },
  data: {
    label: 'sales',
    kind: 'domain',
    metadata: {},
    sourceRange: null,
    direction: 'RIGHT',
  },
};

vi.mock('@xyflow/react', () => ({
  Background: () => <div data-testid="background" />,
  BackgroundVariant: { Dots: 'dots' },
  Controls: ({
    fitViewOptions,
    onFitView,
  }: {
    fitViewOptions?: { minZoom?: number };
    onFitView?: () => void;
  }) => (
    <button
      data-testid="controls"
      data-fit-min-zoom={fitViewOptions?.minZoom}
      onClick={onFitView}
    >
      Controls
    </button>
  ),
  MiniMap: () => <div data-testid="minimap" />,
  ReactFlow: ({
    children,
    fitViewOptions,
    minZoom,
    onMoveStart,
  }: {
    children: React.ReactNode;
    fitViewOptions?: { minZoom?: number };
    minZoom?: number;
    onMoveStart?: (event: MouseEvent, viewport: unknown) => void;
  }) => (
    <div
      data-testid="react-flow"
      data-fit-min-zoom={fitViewOptions?.minZoom}
      data-min-zoom={minZoom}
      onMouseDown={(event) =>
        onMoveStart?.(event.nativeEvent, { x: 0, y: 0, zoom: 1 })
      }
    >
      {children}
    </div>
  ),
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => children,
  useReactFlow: () => ({ fitView: vi.fn(async () => true) }),
}));

vi.mock('./useGraphExport', () => ({
  useGraphExport: mocks.useGraphExport,
}));

vi.mock('./useGraphLayout', () => ({
  useGraphLayout: () => ({
    nodes: [node],
    edges: [],
    loading: false,
    error: null,
  }),
}));

vi.mock('./useGraphSync', () => ({
  useGraphSync: () => ({
    selectedNodeId: null,
    onNodeClick: vi.fn(),
  }),
}));

vi.mock('./useReadableGraphViewport', () => ({
  useReadableGraphViewport: () => mocks.viewport,
}));

const graphResult: BrowserGraphResult = {
  workspace_revision: 1,
  mode: 'domain',
  graph: {
    schema_version: 1,
    nodes: [],
    edges: [],
  },
};

const props: GraphPanelProps = {
  graphResult,
  mode: 'domain',
  onModeChange: vi.fn(),
};

beforeEach(() => {
  mocks.useGraphExport.mockClear();
  mocks.viewport.showMiniMap = false;
});

afterEach(cleanup);

test('shares readable fit options with React Flow and its fit control', () => {
  render(<GraphPanel {...props} />);

  expect(screen.getByTestId('react-flow').getAttribute('data-min-zoom')).toBe(
    '0.1',
  );
  expect(
    screen.getByTestId('react-flow').getAttribute('data-fit-min-zoom'),
  ).toBe('0.6');
  expect(screen.getByTestId('controls').getAttribute('data-fit-min-zoom')).toBe(
    '0.6',
  );
});

test('renders the minimap only when the responsive policy enables it', () => {
  const { rerender } = render(<GraphPanel {...props} />);
  expect(screen.queryByTestId('minimap')).toBeNull();

  mocks.viewport.showMiniMap = true;
  rerender(<GraphPanel {...props} />);
  expect(screen.getByTestId('minimap')).toBeTruthy();
});

test('shares the graph canvas ref with export behavior', () => {
  render(<GraphPanel {...props} />);

  expect(mocks.useGraphExport).toHaveBeenCalledOnce();
  expect(mocks.useGraphExport).toHaveBeenCalledWith(
    expect.objectContaining({ current: expect.any(HTMLDivElement) }),
  );
});
