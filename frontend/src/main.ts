// SPA bootstrap entry (F-19 / §11.1): wire the Tailwind stylesheet, register every screen Custom
// Element (side-effect imports → `customElements.define`), restore the session, handle a magic-link
// landing, mount the global error banner, and start the router.
import './styles/tailwind.css';
import './components/error-banner';
import './components/entrypoint-screen';
import './components/sample-response-screen';
import './components/capture-email-screen';
import './components/guidebook-screen';
import './components/template-screen';
import './components/llm-key-msg-screen';
import './components/processing-screen';

import { ApplicationError, messageFor } from './api/errors';
import { handleMagicLinkLanding, type LandingOutcome } from './boot/magic-link-landing';
import { rehydrateWorkspaceLead } from './boot/workspace-rehydrate';
import { start } from './router/router';
import { isProtectedPath } from './router/routes';
import { showBanner } from './state/error-banner';
import { initSession, lead } from './state/session';

/** SPA bootstrap; exported for tests (the module-level call below runs it in production). */
export async function bootstrap(): Promise<void> {
  initSession();
  // The banner lives outside the router's #root so it survives screen changes (§11.3 / §11.4).
  document.body.prepend(document.createElement('error-banner'));

  let outcome: LandingOutcome = 'none';
  try {
    outcome = await handleMagicLinkLanding();
    if (outcome === 'resolved') {
      // Land the resolved session in the workspace; the router renders it below.
      history.replaceState(null, '', '/workspace');
    } else if (outcome === 'expired') {
      showBanner(messageFor('ERR_INVALID_MAGIC_LINK'));
    }
  } catch (error) {
    showBanner(
      error instanceof ApplicationError
        ? messageFor(error.code)
        : 'Something went wrong. Please try again.',
    );
  }

  if (outcome === 'none' && lead.value === null && isProtectedPath(window.location.pathname)) {
    // Hard reload / direct visit of a protected route: sessionStorage restores only magicLink,
    // so the lead must be rehydrated before the first render (US-03, §11.2).
    await rehydrateWorkspaceLead();
  }

  start();
}

void bootstrap();
