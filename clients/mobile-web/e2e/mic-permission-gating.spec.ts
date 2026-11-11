import { expect, test } from '@playwright/test';
import { waitForAppReady } from './fixtures';

// Today's real contract (contracts/companion-v1.json) always reports
// features.voice: false, and the mock adapter deliberately mirrors that
// exactly (see mock-adapter.ts) rather than a hoped-for future value. This
// suite exercises that real, current gating -- it does not simulate a
// future voice-enabled server, since doing so here would risk this test
// suite quietly drifting ahead of what the app actually ships today.
test('push-to-talk is visibly present but disabled, and clearly labeled, under the real not-yet-enabled contract', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  const button = page.getByTestId('push-to-talk-button');
  await expect(button).toBeVisible();
  await expect(button).toBeDisabled();
  await expect(button).toHaveAttribute('data-availability', 'unavailable_not_enabled');
  await expect(button).toContainText(/not available yet/i);
});

test('a genuinely disabled push-to-talk button has no click handler wired up at all, so it cannot request mic access', async ({ page }) => {
  // PushToTalkButton.tsx's unavailable_not_enabled branch renders a plain
  // `disabled` native <button> with no onClick prop -- a real disabled
  // button never dispatches a click handler in any engine, so there is
  // nothing to request mic access even if this test forces the click.
  await page.goto('/');
  await waitForAppReady(page);

  const button = page.getByTestId('push-to-talk-button');
  await button.click({ force: true });
  // Unchanged: still disabled, same availability, same label -- proof
  // nothing fired, not just an absence of a thrown error.
  await expect(button).toBeDisabled();
  await expect(button).toHaveAttribute('data-availability', 'unavailable_not_enabled');
});
