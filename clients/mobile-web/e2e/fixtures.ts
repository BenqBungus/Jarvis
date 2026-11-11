import { expect, type Page } from '@playwright/test';

/** Waits for the app to finish its initial mock capabilities/status fetch
 * (the composer becomes usable once that resolves). All e2e tests run
 * against the production build's default mode (mock -- see
 * playwright.config.ts's comment on why `?mode=` overrides don't apply
 * here), so there is never a real network dependency in this suite. */
export async function waitForAppReady(page: Page): Promise<void> {
  await expect(page.getByTestId('mock-mode-badge')).toBeVisible();
  await expect(page.getByTestId('composer-input')).toBeEnabled();
}

export async function submitTask(page: Page, text: string): Promise<void> {
  await page.getByTestId('composer-input').fill(text);
  await page.getByTestId('composer-submit').click();
}
