import { expect, test } from '@playwright/test';
import { submitTask, waitForAppReady } from './fixtures';

test('animation is disabled when the OS reduced-motion preference is set', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await waitForAppReady(page);

  await submitTask(page, 'default mock task');
  const pulsing = page.locator('.animated-pulse').first();
  await expect(pulsing).toBeVisible();

  const animationName = await pulsing.evaluate((el) => getComputedStyle(el).animationName);
  expect(animationName).toBe('none');
});

test('animation is enabled with no motion preference (baseline, so the reduce case above is a real contrast)', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/');
  await waitForAppReady(page);

  await submitTask(page, 'default mock task');
  const pulsing = page.locator('.animated-pulse').first();
  await expect(pulsing).toBeVisible();

  const animationName = await pulsing.evaluate((el) => getComputedStyle(el).animationName);
  expect(animationName).not.toBe('none');
});
