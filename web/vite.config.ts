import { VitePWA } from 'vite-plugin-pwa';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/modelable/playground/',
  publicDir: 'public',
  plugins: [
    VitePWA({
      registerType: 'prompt',
      scope: '/modelable/playground/',
      workbox: {
        globPatterns: [
          '**/*.{js,css,html,wasm,mjs,zip,json,whl,ttf,woff,woff2,png}',
        ],
        globIgnores: ['fixtures/**'],
        maximumFileSizeToCacheInBytes: 30 * 1024 * 1024,
        navigateFallback: 'index.html',
      },
      manifest: {
        name: 'Modelable Playground',
        short_name: 'Modelable',
        start_url: '/modelable/playground/',
        display: 'standalone',
        background_color: '#ffffff',
        theme_color: '#1a1a2e',
        icons: [
          {
            src: 'icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: 'icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
          },
        ],
      },
    }),
  ],
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
