import { expect, test } from '@playwright/test';
import { waitForAppReady } from './fixtures';

test('shows an honest offline banner when the browser loses its network connection, and recovers', async ({ page, context }) => {
  await page.goto('/');
  await waitForAppReady(page);

  const banner = page.getByTestId('connection-banner');
  await expect(banner).toHaveAttribute('data-summary', 'online');

  await context.setOffline(true);
  // The app reacts to the browser's own online/offline events (instant),
  // not a poll interval -- no arbitrary wait needed.
  await expect(banner).toHaveAttribute('data-summary', 'offline_browser');
  await expect(banner).toContainText(/offline/i);

  await context.setOffline(false);
  await expect(banner).toHaveAttribute('data-summary', 'online');
});
