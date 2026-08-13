import { expect, test } from '@playwright/test';
import { waitForReady } from './helpers';

/**
 * Responsive visual-regression coverage for Phase 5 of the Playground UI
 * uplift plan (docs/superpowers/plans/2026-08-13-playground-ui-uplift.md):
 * "Add ... responsive visual regression coverage" at 390px, 768px, 1024px,
 * and 1440px, in both light and dark theme.
 *
 * These tests are skipped by default (see RUN_VISUAL_REGRESSION below).
 * Screenshot baselines can only be trusted when captured against a real,
 * fully-initialized browser compiler (Pyodide plus the compiled wheel). An
 * environment without network access to vendor those assets will only ever
 * show the permanent "Compiler runtime initialization failed" error state
 * instead of the real UI, so a baseline captured there would be actively
 * wrong -- it would not fail here (nothing to diff against yet) but would
 * fail every real run afterward once compared against the correct UI.
 *
 * To seed or refresh baselines, run this file in a trusted environment
 * with normal network access (CI, or a developer machine) with:
 *
 *   VISUAL_REGRESSION=1 npx playwright test tests/visual-regression.spec.ts --update-snapshots
 *
 * then commit the resulting PNGs under
 * tests/visual-regression.spec.ts-snapshots/. Once baselines exist, run the
 * same command without --update-snapshots to verify a change against them,
 * or set VISUAL_REGRESSION=1 permanently for a CI job dedicated to this
 * coverage.
 */
const RUN_VISUAL_REGRESSION = process.env.VISUAL_REGRESSION === '1';

const breakpoints = [
  { name: '390', width: 390, height: 844 },
  { name: '768', width: 768, height: 1024 },
  { name: '1024', width: 1024, height: 800 },
  { name: '1440', width: 1440, height: 900 },
];

const themes = ['light', 'dark'] as const;

// Fixtures (like `page`) are resolved before a test body runs, so a
// `test.skip()` call inside the body would still launch a browser for
// every skipped run. Instead, only register the real tests -- which need
// that fixture -- when explicitly opted in; otherwise register a single
// fixture-free placeholder so the file still reports as skipped rather
// than "no tests found".
if (RUN_VISUAL_REGRESSION) {
  for (const theme of themes) {
    for (const breakpoint of breakpoints) {
      test(`playground at ${breakpoint.width}px in ${theme} theme matches its baseline`, async ({
        page,
      }) => {
        await page.addInitScript((value: string) => {
          localStorage.setItem('modelable:theme', value);
        }, theme);
        await page.setViewportSize({
          width: breakpoint.width,
          height: breakpoint.height,
        });
        await page.goto('?test=1');
        await waitForReady(page);

        await expect(page).toHaveScreenshot(
          `playground-${breakpoint.name}-${theme}.png`,
          { fullPage: true, animations: 'disabled' },
        );
      });
    }
  }
} else {
  test.skip(
    'responsive visual-regression coverage (opt-in via VISUAL_REGRESSION=1, see file header)',
    () => {},
  );
}
