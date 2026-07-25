import { Position } from '@xyflow/react';

import type { LayoutDirection } from '../graph-types';

export interface HandlePositions {
  target: Position;
  source: Position;
}

/** Keep handles on the sides the layout actually flows between. */
export function handlePositions(direction: LayoutDirection): HandlePositions {
  return direction === 'DOWN'
    ? { target: Position.Top, source: Position.Bottom }
    : { target: Position.Left, source: Position.Right };
}
