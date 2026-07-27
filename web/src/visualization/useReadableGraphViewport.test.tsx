// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import type { GraphNode } from './graph-types';
import { RESIZE_FIT_DEBOUNCE_MS } from './graph-viewport';
import { useReadableGraphViewport } from './useReadableGraphViewport';

const mocks = vi.hoisted(() => ({
  fitView: vi.fn(async () => true),
  getNodesBounds: vi.fn(() => ({
    x: 20,
    y: 30,
    width: 2000,
    height: 1000,
  })),
  getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 0.8 })),
  setViewport: vi.fn(async () => true),
}));

vi.mock('@xyflow/react', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@xyflow/react')>()),
  useReactFlow: () => ({
    fitView: mocks.fitView,
    getNodesBounds: mocks.getNodesBounds,
    getViewport: mocks.getViewport,
    setViewport: mocks.setViewport,
  }),
}));

let animationFrames: FrameRequestCallback[] = [];
let resizeCallback: ResizeObserverCallback | null = null;

function graphNode(id: string): GraphNode {
  return {
    id,
    position: { x: 0, y: 0 },
    data: {
      label: id,
      kind: 'entity',
      metadata: {},
      sourceRange: null,
      direction: 'DOWN',
    },
  };
}

function setCanvasRect(
  element: HTMLDivElement,
  width: number,
  height: number,
): void {
  vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    right: width,
    bottom: height,
    left: 0,
    width,
    height,
    toJSON: () => ({}),
  });
}

function runAnimationFrames(): void {
  const callbacks = animationFrames;
  animationFrames = [];
  for (const callback of callbacks) callback(0);
}

function resizeCanvas(
  target: HTMLDivElement,
  width: number,
  height: number,
): void {
  setCanvasRect(target, width, height);
  resizeCallback?.(
    [
      {
        target,
        contentRect: target.getBoundingClientRect(),
      } as unknown as ResizeObserverEntry,
    ],
    {} as ResizeObserver,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  mocks.fitView.mockClear();
  mocks.getNodesBounds.mockClear();
  mocks.getViewport.mockClear();
  mocks.setViewport.mockClear();
  animationFrames = [];
  resizeCallback = null;
  vi.stubGlobal(
    'requestAnimationFrame',
    (callback: FrameRequestCallback): number => {
      animationFrames.push(callback);
      return animationFrames.length;
    },
  );
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    animationFrames[id - 1] = () => undefined;
  });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('fits a completed layout and refits a resized untouched canvas', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 700, 500);
  const nodes = [graphNode('one')];

  const { result } = renderHook(() =>
    useReadableGraphViewport(containerRef, nodes),
  );
  await act(async () => runAnimationFrames());

  expect(mocks.fitView).toHaveBeenLastCalledWith(result.current.fitViewOptions);
  expect(result.current.showMiniMap).toBe(false);

  act(() => resizeCanvas(containerRef.current!, 900, 600));
  await act(async () =>
    vi.advanceTimersByTimeAsync(RESIZE_FIT_DEBOUNCE_MS),
  );

  expect(mocks.fitView).toHaveBeenCalledTimes(2);
  expect(result.current.showMiniMap).toBe(false);
});

test('aligns an overflowing graph to the readable leading edge', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 500, 400);
  const nodes = [graphNode('one')];

  renderHook(() => useReadableGraphViewport(containerRef, nodes));
  await act(async () => {
    runAnimationFrames();
    await Promise.resolve();
  });

  expect(mocks.setViewport).toHaveBeenCalledWith({
    x: 8,
    y: 0,
    zoom: 0.8,
  });
});

test('does not refit resize after pointer navigation begins', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 700, 500);
  const nodes = [graphNode('one')];

  const { result } = renderHook(() =>
    useReadableGraphViewport(containerRef, nodes),
  );
  await act(async () => runAnimationFrames());

  act(() =>
    result.current.onMoveStart(new MouseEvent('mousedown'), {
      x: 0,
      y: 0,
      zoom: 1,
    }),
  );
  act(() => resizeCanvas(containerRef.current!, 1000, 700));
  await act(async () =>
    vi.advanceTimersByTimeAsync(RESIZE_FIT_DEBOUNCE_MS),
  );

  expect(mocks.fitView).toHaveBeenCalledTimes(1);
});

test('a new node array establishes a new initial fit', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 700, 500);
  const first = [graphNode('one')];

  const { rerender } = renderHook(
    ({ nodes }) => useReadableGraphViewport(containerRef, nodes),
    { initialProps: { nodes: first } },
  );
  await act(async () => runAnimationFrames());
  rerender({ nodes: [graphNode('two')] });
  await act(async () => runAnimationFrames());

  expect(mocks.fitView).toHaveBeenCalledTimes(2);
});

test('fit control restores responsive fitting after manual navigation', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 700, 500);
  const nodes = [graphNode('one')];

  const { result } = renderHook(() =>
    useReadableGraphViewport(containerRef, nodes),
  );
  await act(async () => runAnimationFrames());
  act(() =>
    result.current.onMoveStart(new MouseEvent('mousedown'), {
      x: 0,
      y: 0,
      zoom: 1,
    }),
  );

  act(() => result.current.onFitView());
  act(() => resizeCanvas(containerRef.current!, 1000, 700));
  await act(async () =>
    vi.advanceTimersByTimeAsync(RESIZE_FIT_DEBOUNCE_MS),
  );

  expect(mocks.fitView).toHaveBeenCalledTimes(2);
});
