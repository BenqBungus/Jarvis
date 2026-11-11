import { expect, test } from '@playwright/test';
import { waitForAppReady } from './fixtures';

test('the composer disables itself while a task is in flight, so a second tap cannot submit a duplicate', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  const input = page.getByTestId('composer-input');
  const submit = page.getByTestId('composer-submit');

  await input.fill('default mock task');
  await submit.click();

  // Still well inside the mock's ~600ms "queued" window -- the composer
  // must already be disabled, not racing to catch up.
  await expect(input).toBeDisabled();
  await expect(submit).toBeDisabled();

  // A second attempted submit while disabled must not create a second
  // conversation entry.
  await input.click({ force: true }).catch(() => {}); // disabled inputs refuse focus in some engines; ignore
  await submit.click({ force: true });

  await expect(page.getByTestId('conversation-entry')).toHaveCount(1);
});

test('two click events fired in the same tick still only produce one task (synchronous guard, not just the disabled attribute)', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  await page.getByTestId('composer-input').fill('default mock task');

  // Two native .click() calls back-to-back inside one page.evaluate() fire
  // before Preact gets a chance to re-render the disabled attribute between
  // them -- this is what actually exercises useTaskPolling's synchronous
  // isSubmittingRef guard. Two separate Playwright .click() calls (which
  // each wait for actionability) can't reproduce this: the first submit
  // already disables the button before a second real click could land.
  await page.evaluate(() => {
    const button = document.querySelector('[data-testid="composer-submit"]') as HTMLButtonElement;
    button.click();
    button.click();
  });

  await expect(page.getByTestId('conversation-entry')).toHaveCount(1);
});
