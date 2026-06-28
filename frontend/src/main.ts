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
import { handleMagicLinkLanding } from './boot/magic-link-landing';
import { start } from './router/router';
import { showBanner } from './state/error-banner';
import { initSession } from './state/session';

async function bootstrap(): Promise<void> {
  initSession();
  // The banner lives outside the router's #root so it survives screen changes (§11.3 / §11.4).
  document.body.prepend(document.createElement('error-banner'));

  try {
    const outcome = await handleMagicLinkLanding();
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

  start();
}

void bootstrap();
