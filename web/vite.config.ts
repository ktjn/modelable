import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/modelable/playground/',
  publicDir: 'public',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
