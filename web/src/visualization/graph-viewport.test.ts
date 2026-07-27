import { describe, expect, test } from 'vitest';

import {
  AUTO_FIT_MAX_ZOOM,
  INTERACTIVE_MIN_ZOOM,
  READABLE_FIT_MIN_ZOOM,
  readableViewportForBounds,
  readableFitOptions,
  shouldShowMiniMap,
} from './graph-viewport';

describe('readableFitOptions', () => {
  test('keeps automatic fitting readable without restricting deliberate overview zoom', () => {
    expect(READABLE_FIT_MIN_ZOOM).toBe(0.8);
    expect(INTERACTIVE_MIN_ZOOM).toBe(0.1);
    expect(AUTO_FIT_MAX_ZOOM).toBe(1);
    expect(readableFitOptions(false)).toMatchObject({
      minZoom: 0.8,
      maxZoom: 1,
    });
  });

  test('reserves additional right-side space when the minimap is visible', () => {
    const withoutMiniMap = readableFitOptions(false);
    const withMiniMap = readableFitOptions(true);
    expect(withMiniMap.padding).not.toEqual(withoutMiniMap.padding);
  });
});

describe('readableViewportForBounds', () => {
  test('aligns overflowing dimensions to the leading canvas padding', () => {
    expect(
      readableViewportForBounds(
        { x: 20, y: 30, width: 2000, height: 1000 },
        { width: 500, height: 400 },
        0.8,
        false,
      ),
    ).toEqual({ x: 8, y: 0, zoom: 0.8 });
  });

  test('centers graph dimensions that fit inside the reserved canvas', () => {
    expect(
      readableViewportForBounds(
        { x: 20, y: 30, width: 100, height: 100 },
        { width: 500, height: 400 },
        0.8,
        false,
      ),
    ).toEqual({ x: 194, y: 116, zoom: 0.8 });
  });
});

describe('shouldShowMiniMap', () => {
  test('shows navigation context only for a dense graph on a roomy canvas', () => {
    expect(shouldShowMiniMap({ width: 900, height: 600 }, 37)).toBe(true);
    expect(shouldShowMiniMap({ width: 500, height: 600 }, 37)).toBe(false);
    expect(shouldShowMiniMap({ width: 900, height: 300 }, 37)).toBe(false);
    expect(shouldShowMiniMap({ width: 900, height: 600 }, 7)).toBe(false);
  });
});
