/// <reference types="vite/client" />

// Injected by vite.config.ts `define`, sourced from infra/env/<env>/<env>.env at build time.
interface ImportMetaEnv {
  readonly VITE_APP_ENV: string;
  readonly VITE_API_BASE_URL: string;
  readonly VITE_MAGIC_LINK_URL_PARAM: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
