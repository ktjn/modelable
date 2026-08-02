import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';
import { replaceSource, sourceOutput, waitForReady } from '../tests/helpers';
import { CURATED_MODELS } from '../src/ai/curated-models';

/**
 * Manual, opt-in suite that drives the playground chat assistant against
 * real WebLLM models over WebGPU, instead of the deterministic
 * `?ai=simulator` provider used by `tests/ai-actions.spec.ts`. It downloads
 * real model weights from Hugging Face / GitHub and needs genuine WebGPU
 * compute, so it is excluded from `npm run test:e2e` and CI.
 *
 * Run with (from `web/`):
 *   npm run build
 *   npm run test:e2e:manual
 *
 * By default this exercises every curated model in
 * `src/ai/curated-models.ts` (~19 GB of downloads the first time — the
 * persistent browser profile in `fixtures.ts` caches them on disk so
 * repeat runs only re-download after a model list or WebLLM version bump).
 * Restrict to a subset for a faster iteration loop:
 *
 *   MODELABLE_WEBLLM_TEST_MODELS=Qwen2.5-0.5B-Instruct-q4f16_1-MLC,Qwen3-1.7B-q4f16_1-MLC npm run test:e2e:manual
 *
 * Run this suite whenever you change anything it exercises: the AI chat
 * pipeline (`web/src/ai/**`), `App.tsx`'s conversation wiring
 * (`runConversation`/`handleAiAccept`/`handleAiDownload`), the curated
 * model list, or the shared Python conversation engine/plan schema
 * (`cli/src/modelable/llm/conversation_*.py`, `conversation_plan.py`) that
 * decides what a chat turn is allowed to change. See
 * `docs/maintainers.md` → "Manual real-model WebLLM chat conformance".
 */

const requestedModels = process.env.MODELABLE_WEBLLM_TEST_MODELS?.split(',')
  .map((id) => id.trim())
  .filter((id) => id.length > 0);

const MODELS_UNDER_TEST = requestedModels ?? CURATED_MODELS.map((m) => m.id);

for (const id of requestedModels ?? []) {
  if (!CURATED_MODELS.some((m) => m.id === id)) {
    throw new Error(
      `MODELABLE_WEBLLM_TEST_MODELS references "${id}", which is not in the curated ` +
        `allowlist (src/ai/curated-models.ts). Use a curated model id or add it there first.`,
    );
  }
}

// Model download + WASM shader compile + first-token latency vary a lot by
// hardware, model size, and network; give generous headroom instead of
// guessing. Individual tests additionally call test.slow() to triple the
// config-level per-test timeout.
const MODEL_READY_TIMEOUT_MS = 8 * 60_000;
const COMPLETION_TIMEOUT_MS = 3 * 60_000;

// Single line, matching the convention in tests/ai-actions.spec.ts: typing a
// multi-line literal through Monaco risks its auto-indent/auto-close-bracket
// behavior mangling the source as each newline is typed.
const EXISTING_CUSTOMER_SOURCE =
  'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid name: string } }';

async function selectAndDownloadRealModel(page: Page, modelId: string): Promise<void> {
  await page.goto('?test=1');
  await waitForReady(page);

  const gpuAvailable = await page.evaluate(async () => {
    if (!('gpu' in navigator)) return false;
    try {
      const adapter = await navigator.gpu.requestAdapter();
      return adapter !== null;
    } catch {
      return false;
    }
  });
  test.skip(
    !gpuAvailable,
    'No WebGPU adapter available in this browser/environment. Run headed ' +
      '(the default for this config) on a machine with a real GPU.',
  );

  const modelSelect = page.getByLabel('AI model');
  await expect(modelSelect.locator(`option[value="${modelId}"]`)).toBeAttached({
    timeout: 15_000,
  });
  await modelSelect.selectOption(modelId);

  await page.getByRole('button', { name: 'Download AI model' }).click();
  await expect(page.getByText('AI model ready')).toBeVisible({
    timeout: MODEL_READY_TIMEOUT_MS,
  });
}

async function sendChatMessage(page: Page, text: string): Promise<void> {
  await page
    .getByPlaceholder('e.g. Add a creditScore field to Customer')
    .fill(text);
  await page.getByRole('button', { name: 'Send' }).click();
}

/** Waits for the pending assistant turn to resolve and asserts it did not error. */
async function waitForAssistantReply(page: Page): Promise<void> {
  await expect(page.getByText('Thinking…')).toBeVisible({ timeout: 5_000 });
  await expect(page.getByText('Thinking…')).toHaveCount(0, {
    timeout: COMPLETION_TIMEOUT_MS,
  });
  await expect(page.getByText('AI_ERROR')).toHaveCount(0);
}

/** Asserts the workspace has no outstanding diagnostics after an AI-applied change. */
async function expectCleanValidation(page: Page): Promise<void> {
  const diagnosticsPanel = page.getByTestId('diagnostics');
  await expect(diagnosticsPanel.locator('li')).toHaveCount(0, { timeout: 10_000 });
}

/** Waits for a source/compilation preview, accepts it, and confirms the outcome. */
async function acceptLatestPreview(page: Page): Promise<void> {
  await expect(
    page.getByText(/^(AI generated source|Compilation preview)$/).last(),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Accept' }).last().click();
  await expect(page.getByText('Accepted').last()).toBeVisible();
}

for (const modelId of MODELS_UNDER_TEST) {
  const { tier, hardwareProfile } =
    CURATED_MODELS.find((m) => m.id === modelId) ?? {
      tier: 'custom',
      hardwareProfile: 'unspecified (override via MODELABLE_WEBLLM_TEST_MODELS)',
    };

  test(`chat use cases work end-to-end — ${modelId} [${tier}] (${hardwareProfile})`, async ({
    page,
  }) => {
    test.slow();
    await selectAndDownloadRealModel(page, modelId);

    await test.step('creates a new entity from scratch and accepts the preview', async () => {
      await sendChatMessage(page, 'Create a Customer entity with a name and email field');
      await waitForAssistantReply(page);
      await expect(page.getByText(`webgpu / ${modelId}`).last()).toBeVisible();
      await acceptLatestPreview(page);
    });

    await test.step('applies a natural-language update, preserving prior fields', async () => {
      await replaceSource(page, EXISTING_CUSTOMER_SOURCE);
      await sendChatMessage(page, 'Add a creditScore field to Customer');
      await waitForAssistantReply(page);
      await acceptLatestPreview(page);

      // The update must extend the existing entity, not replace it: the
      // original key field must survive alongside the newly added field.
      await expect(sourceOutput(page)).toContainText('customerId');
      await expect(sourceOutput(page)).toContainText(/creditScore/i);
      await expectCleanValidation(page);
    });

    await test.step('suggests and accepts a projection for an existing entity', async () => {
      await replaceSource(page, EXISTING_CUSTOMER_SOURCE);
      await page.getByRole('button', { name: 'Suggest projection' }).click();
      await waitForAssistantReply(page);
      await acceptLatestPreview(page);

      // A real projection definition, not just an explanation, must have
      // been written and it must validate cleanly against the compiler.
      await expect(sourceOutput(page)).toContainText(/projection/i);
      await expectCleanValidation(page);
    });

    await test.step('explains the workspace', async () => {
      await page.getByRole('button', { name: 'Explain workspace' }).click();
      await waitForAssistantReply(page);
      await expect(page.getByText('AI explanation').last()).toBeVisible();
    });

    await test.step('generates a new entity and discards the preview without applying it', async () => {
      const sourceBefore = await sourceOutput(page).innerText();

      await sendChatMessage(page, 'Create an Invoice entity with an amount field');
      await waitForAssistantReply(page);
      await expect(
        page.getByText(/^(AI generated source|Compilation preview)$/).last(),
      ).toBeVisible();
      await page.getByRole('button', { name: 'Discard' }).last().click();
      await expect(page.getByText('Discarded').last()).toBeVisible();

      await expect(sourceOutput(page)).toHaveText(sourceBefore);
    });
  });
}
