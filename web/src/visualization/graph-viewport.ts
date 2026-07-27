import type { FitViewOptions, Viewport } from '@xyflow/react';

export const READABLE_FIT_MIN_ZOOM = 0.8;
export const AUTO_FIT_MAX_ZOOM = 1;
export const INTERACTIVE_MIN_ZOOM = 0.1;
export const RESIZE_FIT_DEBOUNCE_MS = 160;

const CANVAS_PADDING_TOP = 24;
const CANVAS_PADDING_RIGHT = 24;
const CANVAS_PADDING_BOTTOM = 64;
const CANVAS_PADDING_LEFT = 24;
const MINIMAP_CANVAS_PADDING_RIGHT = 164;
const MINIMAP_MIN_CANVAS_WIDTH = 640;
const MINIMAP_MIN_CANVAS_HEIGHT = 360;
const MINIMAP_MIN_NODE_COUNT = 10;

export interface CanvasSize {
  width: number;
  height: number;
}

export interface GraphBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function shouldShowMiniMap(
  size: CanvasSize,
  nodeCount: number,
): boolean {
  return (
    size.width >= MINIMAP_MIN_CANVAS_WIDTH &&
    size.height >= MINIMAP_MIN_CANVAS_HEIGHT &&
    nodeCount >= MINIMAP_MIN_NODE_COUNT
  );
}

export function readableFitOptions(showMiniMap: boolean): FitViewOptions {
  return {
    minZoom: READABLE_FIT_MIN_ZOOM,
    maxZoom: AUTO_FIT_MAX_ZOOM,
    padding: {
      top: `${CANVAS_PADDING_TOP}px`,
      right: `${
        showMiniMap
          ? MINIMAP_CANVAS_PADDING_RIGHT
          : CANVAS_PADDING_RIGHT
      }px`,
      bottom: `${CANVAS_PADDING_BOTTOM}px`,
      left: `${CANVAS_PADDING_LEFT}px`,
    },
  };
}

export function readableViewportForBounds(
  bounds: GraphBounds,
  canvas: CanvasSize,
  zoom: number,
  showMiniMap: boolean,
): Viewport {
  const rightPadding = showMiniMap
    ? MINIMAP_CANVAS_PADDING_RIGHT
    : CANVAS_PADDING_RIGHT;
  const availableWidth = Math.max(
    0,
    canvas.width - CANVAS_PADDING_LEFT - rightPadding,
  );
  const availableHeight = Math.max(
    0,
    canvas.height - CANVAS_PADDING_TOP - CANVAS_PADDING_BOTTOM,
  );
  const scaledWidth = bounds.width * zoom;
  const scaledHeight = bounds.height * zoom;
  const x =
    CANVAS_PADDING_LEFT +
    (scaledWidth <= availableWidth
      ? (availableWidth - scaledWidth) / 2
      : 0) -
    bounds.x * zoom;
  const y =
    CANVAS_PADDING_TOP +
    (scaledHeight <= availableHeight
      ? (availableHeight - scaledHeight) / 2
      : 0) -
    bounds.y * zoom;
  return { x, y, zoom };
}
