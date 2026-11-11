import { expect, test } from '@playwright/test';
import { submitTask, waitForAppReady } from './fixtures';

test('a failed task shows the real error message, never a success-looking result', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  await submitTask(page, 'this should fail please');
  await expect(page.getByTestId('task-progress')).toHaveAttribute('data-state', 'failed', { timeout: 5_000 });
  await expect(page.getByTestId('task-error')).toContainText(/simulated failure/i);
  await expect(page.getByTestId('task-result')).toHaveCount(0);

  await page.getByTestId('dismiss-task-button').click();
  await expect(page.getByTestId('conversation-entry')).toContainText(/simulated failure/i);
});

test('a transient poll failure recovers on its own without ever showing a submit-failed dead end', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  await submitTask(page, 'flaky please');
  // The mock throws once on the first getTask() poll, then behaves like the
  // default lifecycle -- it should still reach completed within the normal
  // window, just possibly after one visible "reconnecting" blip.
  await expect(page.getByTestId('task-progress')).toHaveAttribute('data-state', 'completed', { timeout: 6_000 });
});
