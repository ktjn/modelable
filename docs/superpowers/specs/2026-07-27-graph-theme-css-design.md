# 2026-07-27 Graph Theme CSS Design

**Implementation Plan:** [Graph Theme CSS Implementation Plan](../plans/2026-07-27-graph-theme-css.md)

## Problem

The playground redesign removed the internal graph-node styles while retaining
the semantic node markup. The later dark-mode work themed React Flow's outer
wrappers, so nodes now inherit a flat surface without padding, borders, type
distinction, or a clear selected state. The graph is technically usable, but
its hierarchy and contrast are weak in both themes.

## Goal

Restore a coherent graph presentation in light and dark themes without changing
the graph model or component structure. Node types should remain distinguishable
without relying on saturated fills, and the canvas, edges, controls, MiniMap,
selection state, and exported SVG should feel like one visual system.

## Design

Keep the existing `graph-node` markup and React Flow classes. Add graph-specific
theme tokens for the canvas, dots, surfaces, borders, muted text, edges,
selection, MiniMap, and restrained semantic accents. Define those tokens in the
default, system-dark, and explicit-dark theme blocks so the browser view and
theme-aware SVG export resolve the same values.

Restore the base node treatment with compact padding, a small radius, a visible
border, and overflow-safe labels. Use the existing one-letter kind marker as a
small badge. Differentiate domain, entity, version, projection, and field nodes
with a restrained accent border and badge treatment rather than full-card
colors. Preserve the dashed version treatment because it communicates a
structural distinction independently of color.

Remove the broad opaque background from React Flow's outer node wrapper so the
inner semantic node owns its complete appearance. Give keyboard focus and
selected nodes a clear theme-aware outline. Increase edge and handle contrast,
while keeping containment edges quieter than projection edges. Theme the
controls and MiniMap with dedicated canvas/surface/border tokens so neither is
washed out in light mode or overly bright in dark mode.

## Scope

The implementation should remain CSS-only unless verification exposes a missing
state hook. It will not alter graph layout, data, interactions, node dimensions,
or export behavior.

## Verification

- Render the graph in explicit light and dark themes and inspect normal,
  selected, and focused nodes.
- Confirm every node kind is distinguishable and labels truncate safely.
- Confirm edges, handles, controls, canvas dots, and MiniMap remain legible.
- Confirm the SVG export uses the active theme without browser-only styling.
- Run the web tests and production build.
- Before committing, run all four repository gates from `cli/` as required by
  `AGENTS.md`.
