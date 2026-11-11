import { render } from 'preact';
import { App } from './app';
import './styles/global.css';

const root = document.getElementById('app');
if (root) render(<App />, root);

// registerType: 'prompt' (vite.config.ts) means updates never swap silently
// underneath an in-flight task poll -- this is the minimal UI for that
// prompt. Dynamically imported so a dev server run (no built SW) doesn't
// need the virtual module to exist.
if ('serviceWorker' in navigator) {
  import('virtual:pwa-register')
    .then(({ registerSW }) => {
      registerSW({
        onNeedRefresh() {
          // eslint-disable-next-line no-alert
          if (window.confirm('A new version of Jarvis Companion is available. Reload now?')) {
            window.location.reload();
          }
        },
      });
    })
    .catch(() => {
      // No SW in this run (e.g. `vite dev`) -- not an error.
    });
}
