import { get } from '../api/client';
import { ApplicationError, messageFor } from '../api/errors';
import { showBanner } from '../state/error-banner';
import { clearSession, lead, magicLink } from '../state/session';

/**
 * Rehydrate `lead` before the first render on a direct visit / hard reload of a protected route:
 * sessionStorage restores only `magicLink`, so without a fresh `GET /api/magic-link/resolve` the
 * workspace would show "no guidebook yet" regardless of the actual binding (US-03, §11.2).
 *
 * Failure semantics (operator decision 2026-07-06): `ERR_INVALID_MAGIC_LINK` clears the session
 * (the router guard then lands on the entrypoint) with a banner; any other failure keeps the
 * session — it may still be valid — but falls back to the public entrypoint with a banner, since
 * a workspace render could not reflect the actual guidebook binding.
 */
export async function rehydrateWorkspaceLead(): Promise<void> {
  const token = magicLink.value;
  if (token === null) {
    return;
  }
  try {
    lead.value = await get('/magic-link/resolve', { magicLink: token });
  } catch (error) {
    if (error instanceof ApplicationError && error.code === 'ERR_INVALID_MAGIC_LINK') {
      clearSession();
      showBanner(messageFor('ERR_INVALID_MAGIC_LINK'));
      return;
    }
    history.replaceState(null, '', '/');
    showBanner(
      error instanceof ApplicationError
        ? messageFor(error.code)
        : 'Something went wrong. Please try again.',
    );
  }
}
