/**
 * Build-time configuration, injected by Vite from the per-environment non-secret source file
 * `infra/envs/<env>/<env>.env` (single source of truth, shared with the backend). Values are baked at
 * build via `vite --mode <env>` — there are no config literals in this module. The runtime
 * environment comes from the `ENV` attribute of that file, not from the hostname (supersedes §11.6's
 * hostname detection — see clarifications).
 */

/** Deployment environment (the `ENV` attribute of the env file). */
export type Environment = 'dev' | 'staging' | 'prod';

/**
 * Type guard for {@link Environment}.
 *
 * @param value - Any value (e.g. the build-injected `VITE_APP_ENV`).
 * @returns `true` iff `value` is a known deployment environment.
 */
export function isEnvironment(value: unknown): value is Environment {
  return value === 'dev' || value === 'staging' || value === 'prod';
}

/** Current deployment environment (from `infra/envs/<env>/<env>.env` via Vite). */
export const ENVIRONMENT = import.meta.env.VITE_APP_ENV as Environment;

/** Backend API base URL (same-origin via CloudFront). */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL as string;

/** Magic-link landing URL parameter name. */
export const MAGIC_LINK_URL_PARAM = import.meta.env.VITE_MAGIC_LINK_URL_PARAM as string;
