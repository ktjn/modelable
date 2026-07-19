import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/modelable/playground/',
  publicDir: 'public',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          return id.includes('/node_modules/monaco-editor/')
            ? 'monaco'
            : undefined;
        },
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
