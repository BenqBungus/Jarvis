import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { VitePWA } from 'vite-plugin-pwa';

// registerType: 'prompt' (not 'autoUpdate'): a task-poll loop can be mid-flight
// when a new version ships, so the app asks before swapping instead of doing
// it silently underneath the user.
//
// The precache glob only ever matches build output -- API responses can never
// be part of it -- and the explicit /v1/ NetworkOnly rule is defense-in-depth
// for a future same-origin deployment. Together these are what make "never
// cache API responses" actually true, not just documented. See
// clients/mobile-web/README.md for the verification that this survives into
// the compiled service worker.
export default defineConfig({
  plugins: [
    preact(),
    VitePWA({
      registerType: 'prompt',
      devOptions: { enabled: false },
      manifest: {
        name: 'Jarvis Companion',
        short_name: 'Jarvis',
        description: 'Mobile companion for the Jarvis Windows assistant.',
        display: 'standalone',
        background_color: '#0a0e14',
        theme_color: '#0a0e14',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest}'],
        navigateFallbackDenylist: [/^\/v1\//],
        runtimeCaching: [
          {
            urlPattern: /\/v1\//,
            handler: 'NetworkOnly',
          },
        ],
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  build: {
    sourcemap: true,
  },
});
