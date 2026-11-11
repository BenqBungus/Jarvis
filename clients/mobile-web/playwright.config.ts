import { defineConfig, devices } from '@playwright/test';

// webServer runs the production build+preview, not `vite dev`: the service
// worker (and therefore the "never cache /v1/*" guarantee) only registers
// meaningfully against a production-like build. All device/viewport/
// reduced-motion/offline behavior here is Playwright emulation -- see
// README.md's verification table for what that does and doesn't prove
// versus a physical iPhone.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'iphone-webkit',
      use: { ...devices['iPhone 14 Pro'], browserName: 'webkit' },
    },
    {
      name: 'iphone-se-webkit',
      use: { ...devices['iPhone SE'], browserName: 'webkit' },
    },
    {
      name: 'mobile-chromium',
      use: { ...devices['Pixel 7'], browserName: 'chromium' },
    },
  ],
});
