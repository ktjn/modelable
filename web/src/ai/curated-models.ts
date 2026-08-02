export type HardwareTier = 'ultra-light' | 'light' | 'balanced' | 'quality' | 'max';

export interface CuratedModelInfo {
  id: string;
  tier: HardwareTier;
  /** Human-readable hardware profile this tier targets. */
  hardwareProfile: string;
}

/**
 * WebLLM ships 150+ prebuilt model/quantization variants. Most are
 * redundant (multiple quant levels of the same weights) or superseded by
 * newer releases, which makes the raw catalog unusable as a picker. This
 * curates one well-regarded instruct model per VRAM tier, from
 * integrated-graphics laptops up to dedicated 8GB+ desktop GPUs, so the UI
 * only offers models worth choosing between.
 *
 * Single source of truth for both `ai.worker.ts` (filters the live WebLLM
 * catalog against these ids) and the manual real-model Playwright suite
 * under `tests-manual/` (parametrizes across these tiers).
 */
export const CURATED_MODELS: readonly CuratedModelInfo[] = [
  {
    id: 'SmolLM2-360M-Instruct-q4f16_1-MLC',
    tier: 'ultra-light',
    hardwareProfile: 'Integrated graphics / very old laptops (~376 MB VRAM)',
  },
  {
    id: 'gemma3-1b-it-q4f16_1-MLC',
    tier: 'light',
    hardwareProfile: 'Low-end / integrated GPU (~711 MB VRAM)',
  },
  {
    id: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC',
    tier: 'light',
    hardwareProfile: 'Low-VRAM default (~945 MB VRAM)',
  },
  {
    id: 'Qwen3-1.7B-q4f16_1-MLC',
    tier: 'balanced',
    hardwareProfile: 'Typical laptop dGPU (~2 GB VRAM)',
  },
  {
    id: 'Llama-3.2-3B-Instruct-q4f16_1-MLC',
    tier: 'balanced',
    hardwareProfile: 'Balanced, well-rounded (~2.3 GB VRAM)',
  },
  {
    id: 'Phi-4-mini-instruct-q4f16_1-MLC',
    tier: 'quality',
    hardwareProfile: 'Reasoning-focused mid tier (~3.4 GB VRAM)',
  },
  {
    id: 'Qwen3.5-4B-q4f16_1-MLC',
    tier: 'quality',
    hardwareProfile: 'Best overall coverage, long context (~3.9 GB VRAM)',
  },
  {
    id: 'Qwen3-8B-q4f16_1-MLC',
    tier: 'max',
    hardwareProfile: 'Gaming laptop / desktop GPU, top quality (~5.7 GB VRAM)',
  },
] as const;

export const CURATED_MODEL_IDS: readonly string[] = CURATED_MODELS.map((m) => m.id);
