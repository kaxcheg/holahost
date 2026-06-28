/// <reference types="vitest/config" />
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import { parse as parseEnvFile } from 'dotenv';
import { defineConfig } from 'vitest/config';

// Non-secret config the frontend bakes into the bundle (a subset of infra/env/<env>/<env>.env).
const CONFIG_KEYS = ['ENV', 'API_BASE_URL', 'MAGIC_LINK_URL_PARAM'] as const;
const DEPLOY_ENVS = ['dev', 'staging', 'prod'] as const;

/**
 * Resolve the non-secret config for a build.
 *
 * The frontend consumes config from the ENVIRONMENT — at deploy, CI (frontend) / Terraform (backend)
 * populate it from infra/env/<env>/<env>.env, so the frontend is a pure env consumer, symmetric with
 * the backend. For local one-command builds it falls back to reading that file directly (the single
 * place that knows the path). Unknown modes (e.g. vitest's "test") resolve to nothing.
 */
function resolveConfig(mode: string): Record<string, string | undefined> {
  // Vitest runs in mode "test"; resolve it against the dev config so config values are non-null in tests.
  const sourceMode = mode === 'test' ? 'dev' : mode;
  let fileEnv: Record<string, string> = {};
  if ((DEPLOY_ENVS as readonly string[]).includes(sourceMode)) {
    const path = resolve(
      import.meta.dirname,
      '..',
      'infra',
      'env',
      sourceMode,
      `${sourceMode}.env`,
    );
    if (existsSync(path)) {
      fileEnv = parseEnvFile(readFileSync(path));
    }
  }
  const resolved: Record<string, string | undefined> = {};
  for (const key of CONFIG_KEYS) {
    resolved[key] = process.env[key] ?? fileEnv[key];
  }
  if ((DEPLOY_ENVS as readonly string[]).includes(sourceMode) && resolved.ENV === undefined) {
    throw new Error(
      `no config for --mode ${mode}: set env vars or provide infra/env/${sourceMode}/${sourceMode}.env`,
    );
  }
  return resolved;
}

// Statics-only SPA: single bundle to dist/ (no code-splitting needed — screens are small, §11.6).
export default defineConfig(({ mode }) => {
  const cfg = resolveConfig(mode);
  return {
    plugins: [tailwindcss()],
    define: {
      'import.meta.env.VITE_APP_ENV': JSON.stringify(cfg.ENV ?? null),
      'import.meta.env.VITE_API_BASE_URL': JSON.stringify(cfg.API_BASE_URL ?? null),
      'import.meta.env.VITE_MAGIC_LINK_URL_PARAM': JSON.stringify(cfg.MAGIC_LINK_URL_PARAM ?? null),
    },
    build: {
      target: 'es2022',
      outDir: 'dist',
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts'],
    },
  };
});
