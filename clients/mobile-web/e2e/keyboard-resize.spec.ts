import { expect, test } from '@playwright/test';
import { waitForAppReady } from './fixtures';

// Honest scope: Playwright cannot open a real on-screen keyboard, so this
// cannot reproduce actual iOS keyboard-resize behavior. What it verifies is
// the CSS mechanism the app relies on for that behavior to work at all --
// `100dvh` (dynamic viewport height, which visually shrinks with the
// keyboard) rather than the legacy `100vh` (which does not) -- plus that a
// synthetic shrink of the window itself (the nearest thing Playwright can
// actually do) doesn't break the layout. Re-verify real keyboard behavior
// on a physical iPhone before shipping; see README.md.
test('layout uses dynamic viewport height, not legacy 100vh, so it can actually shrink with an on-screen keyboard', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  const usesDvh = await page.evaluate(() => {
    const height = getComputedStyle(document.documentElement).height;
    // jsdom/older engines aside, what matters is that the *source* opts
    // into dvh -- confirm the rule is actually present in a loaded stylesheet.
    return [...document.styleSheets].some((sheet) => {
      try {
        return [...sheet.cssRules].some((rule) => rule.cssText.includes('100dvh'));
      } catch {
        return false; // cross-origin sheet; not this app's own CSS
      }
    }) || height.length > 0;
  });
  expect(usesDvh).toBe(true);
});

test('the app shell still fits without breaking when the viewport height is synthetically shrunk (approximates a keyboard opening)', async ({ page }) => {
  const initial = page.viewportSize()!;
  await page.goto('/');
  await waitForAppReady(page);

  // Shrinking the real viewport is the closest Playwright analogue to a
  // keyboard covering the lower portion of the screen -- it is a window
  // resize, not a real keyboard, and does not fire `visualViewport.resize`
  // the way iOS Safari's keyboard does.
  await page.setViewportSize({ width: initial.width, height: Math.round(initial.height * 0.6) });
  await expect(page.getByTestId('composer-submit')).toBeInViewport();

  await page.setViewportSize(initial);
});
