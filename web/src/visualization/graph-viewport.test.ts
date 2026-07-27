import { describe, expect, test } from 'vitest';

import {
  AUTO_FIT_MAX_ZOOM,
  INTERACTIVE_MIN_ZOOM,
  READABLE_FIT_MIN_ZOOM,
  readableFitOptions,
  shouldShowMiniMap,
} from './graph-viewport';

describe('readableFitOptions', () => {
  test('keeps automatic fitting readable without restricting deliberate overview zoom', () => {
    expect(READABLE_FIT_MIN_ZOOM).toBe(0.6);
    expect(INTERACTIVE_MIN_ZOOM).toBe(0.1);
    expect(AUTO_FIT_MAX_ZOOM).toBe(1);
    expect(readableFitOptions(false)).toMatchObject({
      minZoom: 0.6,
      maxZoom: 1,
    });
  });

  test('reserves additional right-side space when the minimap is visible', () => {
    const withoutMiniMap = readableFitOptions(false);
    const withMiniMap = readableFitOptions(true);
    expect(withMiniMap.padding).not.toEqual(withoutMiniMap.padding);
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
