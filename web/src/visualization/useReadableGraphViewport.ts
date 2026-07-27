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
  const { fitView } = useReactFlow();
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

  const fitReadableView = useCallback(() => {
    const bounds = containerRef.current?.getBoundingClientRect();
    const options =
      bounds === undefined
        ? fitViewOptionsRef.current
        : optionsForSize({ width: bounds.width, height: bounds.height });
    if (bounds !== undefined) {
      previousSizeRef.current = {
        width: bounds.width,
        height: bounds.height,
      };
    }
    void fitView(options);
  }, [containerRef, fitView, optionsForSize]);

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
        void fitView(fitViewOptionsRef.current);
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
  }, [containerRef, fitView, nodes.length, optionsForSize]);

  const onMoveStart = useCallback<OnMoveStart>((event) => {
    if (event !== null) {
      userNavigatedRef.current = true;
    }
  }, []);

  const onFitView = useCallback(() => {
    userNavigatedRef.current = false;
  }, []);

  return { fitViewOptions, showMiniMap, onMoveStart, onFitView };
}
