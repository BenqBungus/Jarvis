import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/preact';
import '@testing-library/jest-dom/vitest';

// Explicit, not implicit: vitest.config.ts sets test.globals: false
// deliberately (no ambient describe/it/expect), so @testing-library/preact's
// own auto-cleanup registration -- which only fires when it detects test
// globals -- never runs on its own. Without this, DOM from every previous
// test in a file stays mounted, and a later getByTestId() that matched one
// element alone starts throwing "multiple elements found".
afterEach(() => {
  cleanup();
});

// jsdom does not implement layout, so scrollIntoView is missing entirely
// (real browsers all have it); ConversationView's autoscroll would
// otherwise throw on every render in tests.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// jsdom does not implement matchMedia; usePrefersReducedMotion and any
// prefers-reduced-motion-aware component would otherwise throw in tests.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
