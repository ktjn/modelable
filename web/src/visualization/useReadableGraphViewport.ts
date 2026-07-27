import {
  useReactFlow,
  type FitViewOptions,
  type OnMoveStart,
} from '@xyflow/react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from 'react';

import type { GraphNode } from './graph-types';
import {
  RESIZE_FIT_DEBOUNCE_MS,
  READABLE_FIT_MIN_ZOOM,
  readableViewportForBounds,
  readableFitOptions,
  shouldShowMiniMap,
  type CanvasSize,
} from './graph-viewport';

export interface ReadableGraphViewport {
  fitViewOptions: FitViewOptions;
  showMiniMap: boolean;
  onMoveStart: OnMoveStart;
  onFitView(): void;
}

function sameSize(left: CanvasSize, right: CanvasSize): boolean {
  return left.width === right.width && left.height === right.height;
}

export function useReadableGraphViewport(
  containerRef: RefObject<HTMLDivElement | null>,
  nodes: GraphNode[],
): ReadableGraphViewport {
  const { fitView, getNodesBounds, getViewport, setViewport } = useReactFlow();
  const [canvasSize, setCanvasSize] = useState<CanvasSize>({
    width: 0,
    height: 0,
  });
  const userNavigatedRef = useRef(false);
  const previousSizeRef = useRef<CanvasSize | null>(null);
  const resizeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showMiniMap = shouldShowMiniMap(canvasSize, nodes.length);
  const fitViewOptions = useMemo(
    () => readableFitOptions(showMiniMap),
    [showMiniMap],
  );
  const fitViewOptionsRef = useRef(fitViewOptions);
  fitViewOptionsRef.current = fitViewOptions;

  const optionsForSize = useCallback(
    (size: CanvasSize): FitViewOptions => {
      setCanvasSize((previous) => (sameSize(previous, size) ? previous : size));
      const next = readableFitOptions(shouldShowMiniMap(size, nodes.length));
      fitViewOptionsRef.current = next;
      return next;
    },
    [nodes.length],
  );

  const alignReadableView = useCallback(async () => {
    const bounds = containerRef.current?.getBoundingClientRect();
    if (bounds === undefined || nodes.length === 0) return;
    const viewport = getViewport();
    if (viewport.zoom > READABLE_FIT_MIN_ZOOM + 0.001) return;
    const canvas = { width: bounds.width, height: bounds.height };
    const graphBounds = getNodesBounds(nodes);
    await setViewport(
      readableViewportForBounds(
        graphBounds,
        canvas,
        viewport.zoom,
        shouldShowMiniMap(canvas, nodes.length),
      ),
    );
  }, [
    containerRef,
    getNodesBounds,
    getViewport,
    nodes,
    setViewport,
  ]);

  const fitReadableView = useCallback(async () => {
    const bounds = containerRef.current?.getBoundingClientRect();
    let options = fitViewOptionsRef.current;
    if (bounds !== undefined) {
      const size = { width: bounds.width, height: bounds.height };
      options = optionsForSize(size);
      previousSizeRef.current = size;
    }
    const fitted = await fitView(options);
    if (fitted) {
      await alignReadableView();
    }
  }, [alignReadableView, containerRef, fitView, optionsForSize]);

  useEffect(() => {
    if (nodes.length === 0) return;
    userNavigatedRef.current = false;
    const frame = requestAnimationFrame(fitReadableView);
    return () => cancelAnimationFrame(frame);
  }, [fitReadableView, nodes]);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry === undefined) return;
      const nextSize = {
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      };
      const previousSize = previousSizeRef.current;
      previousSizeRef.current = nextSize;
      optionsForSize(nextSize);

      if (
        previousSize === null ||
        sameSize(previousSize, nextSize) ||
        nodes.length === 0 ||
        userNavigatedRef.current
      ) {
        return;
      }

      if (resizeTimerRef.current !== null) {
        clearTimeout(resizeTimerRef.current);
      }
      resizeTimerRef.current = setTimeout(() => {
        resizeTimerRef.current = null;
        void fitReadableView();
      }, RESIZE_FIT_DEBOUNCE_MS);
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      if (resizeTimerRef.current !== null) {
        clearTimeout(resizeTimerRef.current);
        resizeTimerRef.current = null;
      }
    };
  }, [containerRef, fitReadableView, nodes.length, optionsForSize]);

  const onMoveStart = useCallback<OnMoveStart>((event) => {
    if (event !== null) {
      userNavigatedRef.current = true;
    }
  }, []);

  const onFitView = useCallback(() => {
    userNavigatedRef.current = false;
    requestAnimationFrame(() => {
      void alignReadableView();
    });
  }, [alignReadableView]);

  return { fitViewOptions, showMiniMap, onMoveStart, onFitView };
}
