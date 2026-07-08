import { MAGIC_LINK_URL_PARAM } from '../config';

/**
 * Read the magic-link token from a URL query string (§11.4).
 *
 * @param search - Query string (defaults to the current `window.location.search`).
 * @param param - Parameter name (defaults to the configured {@link MAGIC_LINK_URL_PARAM}).
 * @returns The token, or `null` if absent/empty.
 */
export function extractMagicLink(
  search: string = window.location.search,
  param: string = MAGIC_LINK_URL_PARAM,
): string | null {
  const value = new URLSearchParams(search).get(param);
  return value ? value : null;
}

/**
 * Drop the query string from the current URL without navigating, so the magic-link token does not
 * linger in the address bar or CDN logs (§10.3 / §11.4).
 */
export function stripQuery(): void {
  history.replaceState(history.state, '', window.location.pathname);
}

/**
 * Strip one trailing slash (the root path stays `/`): `/x/` ≡ `/x` for every route and for the
 * magic-link landing path (US-03 / §11.1 / §11.4).
 */
export function normalizePath(path: string): string {
  return path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path;
}
