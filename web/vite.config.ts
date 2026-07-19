import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/modelable/playground/',
  publicDir: 'public',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rolldownOptions: {
      output: {
        manualChunks(id) {
          return id.includes('/node_modules/monaco-editor/')
            ? 'monaco'
            : undefined;
        },
      },
    },
  },
  worker: {
    rolldownOptions: {
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
