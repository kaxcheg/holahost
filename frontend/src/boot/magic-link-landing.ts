import { get } from '../api/client';
import { ApplicationError } from '../api/errors';
import { lead, magicLink } from '../state/session';
import { extractMagicLink, stripQuery } from '../utils/url';

/** Outcome of the magic-link landing flow, for the caller to route/notify on (§11.4). */
export type LandingOutcome = 'none' | 'resolved' | 'expired';

/**
 * Handle the magic-link landing (`/?ml=<token>`, §11.4 / §10.3): strip the token from the URL,
 * resolve it, and populate the session.
 *
 * @returns `'none'` if no token was present, `'resolved'` on success (session populated), or
 *   `'expired'` on `ERR_INVALID_MAGIC_LINK` (session cleared). Other errors propagate.
 * @throws ApplicationError for non-auth failures (rate limit, internal), handled by the caller.
 */
export async function handleMagicLinkLanding(): Promise<LandingOutcome> {
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
