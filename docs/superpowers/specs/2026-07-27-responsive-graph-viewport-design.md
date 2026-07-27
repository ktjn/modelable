# 2026-07-27 Responsive Graph Viewport Design

## Status

Approved for implementation on 2026-07-27.

**Implementation Plan:** [Responsive Graph Viewport Implementation Plan](../plans/2026-07-27-responsive-graph-viewport.md)

This specification follows the shipped
[Playground Visualization MVP](archived/2026-07-21-playground-visualization-design.md)
and [Graph Theme CSS](archived/2026-07-27-graph-theme-css-design.md) designs.

## Problem

The graph's semantic styling is present, but the rendered composition is still
hard to use. React Flow fits every layout into the available canvas without a
readability floor. In the default test workspace, Entity mode renders 37 nodes
at approximately 17.6% zoom, reducing a 180px node to about 32px on screen.
Labels are unreadable even though the complete graph technically fits.

The fixed 202px by 152px MiniMap occupies a large share of the normal desktop
canvas, and the bottom-left controls can cover nodes. Domain and Lineage modes
remain readable but place meaningful content beneath these overlays.

The graph also fails to benefit from larger displays. The workbench is capped
at 120rem, leaving 320px unused on each side of a 2560px viewport, and resizing
the graph panel does not recompute the initial viewport. A graph fitted in a
small panel therefore remains unnecessarily small after the panel or browser
grows.

## Goal

Make every graph mode readable and visually balanced across light and dark
themes, while allowing larger displays and widened panels to reveal more graph
content. Dense graphs should prefer readable nodes with panning over a
whole-graph thumbnail.

## Non-goals

- Changing compiler graph data or browser protocol contracts.
- Adding graph filtering, clustering, search, drill-down, or saved layouts.
- Replacing ELK or React Flow.
- Persisting zoom or pan state between sessions.
- Redesigning the surrounding editor, explorer, or diagnostics panels.

## Chosen approach

Use a responsive readable viewport rather than unconditional whole-graph fit.
Keep the existing ELK layout and React Flow interaction model, but make the
initial viewport mode-aware, size-aware, and bounded by a legibility floor.
Pair that behavioral change with smaller overlays, explicit overlay clearance,
and a compact toolbar.

This approach was selected over:

- a CSS-only cleanup, which cannot prevent dense graphs from shrinking below
  readable size; and
- overview/detail navigation or clustering, which would add new product
  behavior beyond a focused graph cleanup.

## Viewport behavior

### Initial fit

After a graph layout completes, fit the graph once with explicit padding and a
minimum readable zoom. The fit may use up to 100% zoom but must not enlarge
normal nodes beyond their authored size.

- Domain and Lineage modes should show the complete graph when it fits at a
  readable scale.
- Entity and Projection modes should stop shrinking at the readability floor.
  Content outside the canvas remains reachable through pan and zoom.
- The readability floor should be chosen from rendered screenshot evidence,
  not from the current React Flow component minimum of 0.1. The implementation
  target is approximately 0.55–0.65, with the exact value finalized during
  visual verification.
- Fit padding must reserve space for any visible controls and MiniMap so the
  initial composition does not place nodes underneath them.

The React Flow component's interactive minimum zoom may remain lower than the
automatic fit floor. Users can deliberately zoom farther out for orientation,
but the application must not begin in an unreadable state.

### Resize response

Observe the actual graph canvas rather than relying only on browser viewport
breakpoints. When the canvas meaningfully changes size because the browser,
editor split, graph split, or bottom panel is resized:

- recompute the fitted viewport if the user has not manually panned or zoomed;
- use newly available width and height to show more content;
- debounce resize-driven fitting so dragging a separator remains smooth; and
- do not reset a viewport that the user has intentionally navigated.

Changing graph mode or receiving a new graph layout resets the interaction
marker and establishes a new initial fit. Incidental React re-renders must not
reset the viewport.

### Fit control

The explicit React Flow "Fit View" control should apply the same readable fit
policy as the initial view. It should not return dense modes to the current
whole-graph thumbnail. Users can still zoom out manually when they want a
complete overview.

## Large-screen behavior

The playground is an IDE-style workbench and should use the available browser
width. Remove the fixed 120rem workbench cap while retaining a full-width
layout and existing resizable-panel constraints. The graph continues to use
the visualization panel's actual dimensions, so widening that panel on an
ultrawide display directly increases visible graph context.

Large screens must not merely add empty margins or stretch node cards. Nodes
retain their authored dimensions; the larger canvas displays more nodes and
edges at a readable scale.

## Overlay and toolbar composition

### MiniMap

- Reduce the MiniMap from its 202px by 152px default footprint.
- Size it responsively within a bounded range so it remains useful on large
  canvases without dominating smaller ones.
- Hide it when the graph is small enough to fit readably without navigation
  context, or when the canvas cannot accommodate it without obscuring content.
- Retain `aria-hidden="true"` because it duplicates the main graph.

### Controls

- Present the React Flow controls as a compact cluster.
- Position them in reserved canvas space rather than over the node layout.
- Preserve accessible names, keyboard focus, zoom, fit, and interactivity
  actions.
- Keep light and dark theme contrast consistent with the graph surfaces.

### Toolbar

- Keep all four mode buttons and both export actions.
- Reduce padding and visual weight so the toolbar gives more space to the
  canvas.
- Allow sensible wrapping or grouping when the panel is narrow instead of
  squeezing labels or overflowing.
- Preserve clear pressed, hover, disabled, and keyboard-focus states.

## Visual treatment

Retain the semantic node system from the Graph Theme CSS design. Refine it only
where screenshot verification shows weak hierarchy:

- keep node text readable at the automatic zoom floor;
- preserve restrained kind accents and dashed version nodes;
- improve edge visibility without letting edges overpower node labels;
- ensure selected and keyboard-focused nodes remain distinct in both themes;
- use canvas dots, overlay surfaces, and borders from graph-specific theme
  tokens; and
- keep SVG export aligned with the active theme.

Layout spacing may be tuned by mode when it improves scanability, but node
dimensions and semantic relationships remain unchanged.

## Accessibility

- Automatic fitting must not reduce text below the selected readability floor.
- Panning and zooming remain keyboard and pointer accessible.
- Controls keep visible focus indicators and accessible labels.
- Color remains supplementary to node shape, badge, border, and line style.
- Reduced-motion users should not receive animated resize fitting.

## Architecture decision scope

No ADR change is required. The shipped
[Playground Visualization MVP](archived/2026-07-21-playground-visualization-design.md)
already assigns rendering and viewport interaction to React Flow and layout to
ELK. This design adjusts presentation and viewport policy within that existing
boundary.

## Testing strategy

### Unit and component tests

- Verify the readable fit options used for dense and sparse modes.
- Verify mode or graph changes permit a new initial fit.
- Verify manual viewport interaction prevents resize-driven reset.
- Verify the explicit fit control uses the readable fit policy.
- Verify MiniMap visibility rules and overlay classes or properties.

### Playwright integration tests

Exercise Domain, Entity, Projection, and Lineage modes at:

- a constrained graph panel on a standard desktop viewport;
- the default desktop panel size;
- a widened graph panel; and
- a 2560px-wide ultrawide viewport.

Assert that:

- dense modes do not start below the readability floor;
- representative node labels remain visible;
- visible controls and the MiniMap do not intersect graph nodes after fitting;
- widening the panel or viewport increases visible graph context;
- the workbench uses the available ultrawide viewport; and
- light and dark themes retain usable contrast.

### Screenshot review

Capture before-and-after screenshots for every graph mode in explicit light
and dark themes. Include a constrained dense graph and an ultrawide dense graph
in the after set. Review composition, label readability, edge clarity, overlay
placement, toolbar density, theme parity, and use of available space.

## Verification

- Run focused web unit and Playwright tests while iterating.
- Run the complete web test suite and production build.
- Inspect the final screenshot matrix at constrained, default, widened, and
  ultrawide sizes.
- Before committing implementation, run all four repository gates from `cli/`
  as required by `AGENTS.md`.
