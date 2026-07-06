import { get } from '../api/client';
import { ApplicationError } from '../api/errors';
import { MAGIC_LINK_PATH } from '../config';
import { lead, magicLink } from '../state/session';
import { extractMagicLink, stripQuery } from '../utils/url';

/** Outcome of the magic-link landing flow, for the caller to route/notify on (§11.4). */
export type LandingOutcome = 'none' | 'resolved' | 'expired';

/**
 * `/claim` and `/claim/` must match: links from already-delivered emails have to work for the whole
 * `GUIDEBOOK_TTL`, across redeploys and contract tweaks (US-03, §11.4).
 */
function normalizePath(path: string): string {
  return path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path;
}

/**
 * Handle the magic-link landing (`<MAGIC_LINK_PATH>?<param>=<token>`, §11.4 / §10.3): only when the SPA
 * is on the frontend-owned landing path, strip the token from the URL, resolve it, and populate the
 * session.
 *
 * @param landingPath - The SPA landing path magic links point to (default: the configured
 *   {@link MAGIC_LINK_PATH}); the flow is a no-op on any other path.
 * @returns `'none'` if not on the landing path or no token was present, `'resolved'` on success
 *   (session populated), or `'expired'` on `ERR_INVALID_MAGIC_LINK` (session cleared). Other errors
 *   propagate.
 * @throws ApplicationError for non-auth failures (rate limit, internal), handled by the caller.
 */
export async function handleMagicLinkLanding(
  landingPath: string = MAGIC_LINK_PATH,
): Promise<LandingOutcome> {
  if (normalizePath(window.location.pathname) !== normalizePath(landingPath)) {
    return 'none';
  }
  const token = extractMagicLink();
  if (!token) {
    return 'none';
  }
  stripQuery();
  try {
    lead.value = await get('/magic-link/resolve', { magicLink: token });
    magicLink.value = token;
    return 'resolved';
  } catch (error) {
    if (error instanceof ApplicationError && error.code === 'ERR_INVALID_MAGIC_LINK') {
      magicLink.value = null;
      lead.value = null;
      return 'expired';
    }
    throw error;
  }
}
