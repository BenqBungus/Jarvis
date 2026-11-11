/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_COMPANION_MODE?: string;
  readonly VITE_COMPANION_BASE_URL?: string;
  readonly VITE_COMPANION_DEV_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
