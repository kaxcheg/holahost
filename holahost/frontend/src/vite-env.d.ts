/// <reference types="vite/client" />

// Injected by vite.config.ts `define`: VITE_APP_ENV / VITE_API_BASE_URL from services/lead-capture/envs/<env>.env;
// VITE_MAGIC_LINK_* from the frontend-owned frontend/.env (the magic-link URL contract).
interface ImportMetaEnv {
  readonly VITE_APP_ENV: string;
  readonly VITE_API_BASE_URL: string;
  readonly VITE_MAGIC_LINK_URL_PARAM: string;
  readonly VITE_MAGIC_LINK_PATH: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
