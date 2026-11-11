// vitest/config's defineConfig (not plain vite's) augments the Vite config
// type with the `test` field this file needs.
import { defineConfig } from 'vitest/config';
import preact from '@preact/preset-vite';

// Deliberately separate from vite.config.ts: VitePWA has no purpose in a
// jsdom unit-test run, and keeping it out of this config avoids an unrelated
// plugin touching the test transform pipeline.
export default defineConfig({
  plugins: [preact()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    css: true,
    exclude: ['e2e/**', 'node_modules/**'],
  },
});
