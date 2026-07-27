import type { FitViewOptions } from '@xyflow/react';

export const READABLE_FIT_MIN_ZOOM = 0.6;
export const AUTO_FIT_MAX_ZOOM = 1;
export const INTERACTIVE_MIN_ZOOM = 0.1;
export const RESIZE_FIT_DEBOUNCE_MS = 160;

const MINIMAP_MIN_CANVAS_WIDTH = 640;
const MINIMAP_MIN_CANVAS_HEIGHT = 360;
const MINIMAP_MIN_NODE_COUNT = 10;

export interface CanvasSize {
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
      top: '24px',
      right: showMiniMap ? '164px' : '24px',
      bottom: '64px',
      left: '64px',
    },
  };
}
