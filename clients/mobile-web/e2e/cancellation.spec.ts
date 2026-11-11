import { expect, test } from '@playwright/test';
import { submitTask, waitForAppReady } from './fixtures';

test('cancelling a running task reaches a cancelled terminal state, cooperatively not instantly', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  await submitTask(page, 'default mock task');
  const cancelButton = page.getByTestId('cancel-task-button');
  await expect(cancelButton).toBeVisible();
  await cancelButton.click();

  // Contract: cancel is cooperative -- it must not claim the terminal state
  // before the next tick actually resolves it.
  await expect(page.getByTestId('task-progress')).toContainText(/cancelling/i);
  await expect(page.getByTestId('task-progress')).toHaveAttribute('data-state', 'cancelled', { timeout: 5_000 });

  await page.getByTestId('dismiss-task-button').click();
  await expect(page.getByTestId('task-progress')).toHaveCount(0);
  await expect(page.getByTestId('conversation-entry')).toContainText(/cancelled/i);
});

test('cancel is offered while non-terminal and disappears once a task is already settled', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  await submitTask(page, 'default mock task');
  await expect(page.getByTestId('cancel-task-button')).toBeVisible();

  await expect(page.getByTestId('task-progress')).toHaveAttribute('data-state', 'completed', { timeout: 5_000 });
  await expect(page.getByTestId('cancel-task-button')).toHaveCount(0);
});
