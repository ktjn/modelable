# Playground UI uplift plan

## Goal

Make the Playground feel like a modern contract-design workbench while
preserving its local-first behavior, compiler semantics, keyboard shortcuts,
accessibility guarantees, and existing light/dark themes.

The current visual baseline was captured with Playwright on 2026-08-13:

- `output/playwright/desktop-initial.png`
- `output/playwright/desktop-graph.png`
- `output/playwright/mobile-initial.png`

## Design direction

Modelable should read as a contract studio: a calm, instrument-like workspace
for writing model definitions, validating them, and inspecting their generated
representations. Use a dark ink shell, warm editor surfaces, and a distinctive
mint/cyan success accent. Keep the palette restrained; reserve amber for
warnings and coral for errors. Use typography and spacing to establish
hierarchy instead of adding decorative effects.

## Phases

### Phase 1 — shell and action hierarchy

- Establish semantic color, surface, border, focus, spacing, and typography
  tokens for both themes.
- Give the workbench a stronger frame and distinguish shell chrome from active
  content surfaces.
- Reduce the toolbar's visual competition: group workspace actions separately
  from the validate/generate flow, and make the primary action state clearer.
- Rework status badges so they communicate user-facing state rather than
  implementation detail.
- Preserve all existing labels, keyboard shortcuts, and callbacks.

Acceptance: the initial desktop and mobile screenshots show clear primary
action hierarchy, visible focus treatment, and no changed compiler behavior.

### Phase 2 — workspace navigation

- Add open-file tabs and stronger selected/unsaved states.
- Improve file actions with labeled affordances, tooltips, and an overflow
  menu for destructive or infrequent commands.
- Add a useful empty workspace state and an import review step.

Acceptance: keyboard users can create, switch, rename, import, and delete files
without relying on icon interpretation.

### Phase 3 — contextual inspection

- Convert the right panel into a contextual inspector for assistant, graph,
  and generated output.
- Add graph selection details, graph loading/error states, and grouped export
  controls.
- Make output artifacts easier to compare, copy, download, and inspect.

Acceptance: selecting a graph node or generated artifact exposes the next useful
action without requiring tab hunting.

### Phase 4 — diagnostics and task feedback

- Turn Problems, Compatibility, and Governance into a compact status drawer
  with counts and meaningful empty states.
- Jump from findings to source locations.
- Make saving, compiling, and recovery states visible but unobtrusive.

Acceptance: a new error is discoverable within one glance and opens directly at
the relevant source location.

### Phase 5 — mobile and command-driven UX

- Replace the compressed desktop layout on small screens with bottom
  navigation and full-screen sheets for files, inspection, output, and
  diagnostics.
- Add a command palette for navigation, validation, generation, target
  selection, and panel switching.
- Add shortcut discovery and responsive visual regression coverage.

Acceptance: the 390px flow supports edit → validate → generate → inspect
without requiring horizontal scrolling or hidden desktop-only controls.

## Verification

Each phase will include Playwright screenshots at 390px, 768px, 1024px, and
1440px, keyboard navigation checks, reduced-motion checks, and both theme
variants. The web typecheck and full Vitest suite remain required after each
implementation slice.
