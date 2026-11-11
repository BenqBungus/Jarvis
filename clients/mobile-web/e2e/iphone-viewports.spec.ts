import { expect, test } from '@playwright/test';
import { waitForAppReady } from './fixtures';

// Runs on every configured project (iphone-webkit, iphone-se-webkit,
// mobile-chromium -- see playwright.config.ts). This proves the layout
// behaves correctly at real iPhone viewport dimensions under a real engine
// (webkit projects) or a mobile-emulated Chromium; it does not prove
// anything about a physical device's actual notch/Dynamic Island geometry
// -- see README.md's verification table.
test('renders without horizontal overflow at the device viewport size', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(viewport!.width);
});

test('the safe-area CSS custom properties are defined on :root (mechanism present, not a claim about real notch geometry)', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  const safeBottomDeclared = await page.evaluate(() => {
    const value = getComputedStyle(document.documentElement).getPropertyValue('--safe-bottom');
    return value.trim().length > 0;
  });
  expect(safeBottomDeclared).toBe(true);
});

test('the bottom composer bar stays reachable within the viewport', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);
  await expect(page.getByTestId('composer-submit')).toBeInViewport();
});
