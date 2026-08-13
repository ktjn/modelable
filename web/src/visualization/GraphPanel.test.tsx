// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import type { BrowserGraphResult } from '../protocol';
import type { GraphNode } from './graph-types';
import { GraphPanel, type GraphPanelProps } from './GraphPanel';

const node: GraphNode = {
  id: 'version:sales.Customer@2',
  type: 'version',
  position: { x: 0, y: 0 },
  data: {
    label: 'Customer@2',
    kind: 'version',
    metadata: { version: 2, change_kind: 'additive' },
    sourceRange: null,
    direction: 'RIGHT',
  },
};

const mocks = vi.hoisted(() => ({
  useGraphExport: vi.fn(() => ({
    exportSvg: vi.fn(),
    exportPng: vi.fn(),
  })),
  viewport: {
    fitViewOptions: {
      minZoom: 0.8,
      maxZoom: 1,
      padding: 0.1,
    },
    showMiniMap: false,
    onMoveStart: vi.fn(),
    onFitView: vi.fn(),
  },
  graphSync: {
    selectedNodeId: null as string | null,
    onNodeClick: vi.fn(),
  },
}));

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
  useGraphSync: () => mocks.graphSync,
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
  mocks.graphSync.selectedNodeId = null;
});

afterEach(cleanup);

test('shares readable fit options with React Flow and its fit control', () => {
  render(<GraphPanel {...props} />);

  expect(screen.getByTestId('react-flow').getAttribute('data-min-zoom')).toBe(
    '0.1',
  );
  expect(
    screen.getByTestId('react-flow').getAttribute('data-fit-min-zoom'),
  ).toBe('0.8');
  expect(screen.getByTestId('controls').getAttribute('data-fit-min-zoom')).toBe(
    '0.8',
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

test('shows no details region when nothing is selected', () => {
  render(<GraphPanel {...props} />);

  expect(
    screen.queryByRole('region', { name: 'Selected node details' }),
  ).toBeNull();
});

test('shows selected node kind, label, and metadata in the details region', () => {
  mocks.graphSync.selectedNodeId = node.id;
  render(<GraphPanel {...props} />);

  const details = screen.getByRole('region', {
    name: 'Selected node details',
  });
  expect(details.textContent).toContain('version');
  expect(details.textContent).toContain('Customer@2');
  expect(details.textContent).toContain('version: 2');
  expect(details.textContent).toContain('change_kind: additive');
});
