import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MAGIC_LINK_PATH } from './config';
import { bannerMessage, clearBanner } from './state/error-banner';
import { lead, magicLink } from './state/session';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe('main bootstrap', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="root"></main>';
    sessionStorage.clear();
    magicLink.value = null;
    lead.value = null;
    clearBanner();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    history.replaceState(null, '', '/');
  });

  it('registers the screens and mounts the entrypoint + error banner', async () => {
    // The test URL is not the magic-link landing path (and has no `?ml=`) → landing is a no-op; the
    // router renders the entrypoint.
    history.replaceState(null, '', '/');
    await import('./main');
    await tick();

    expect(customElements.get('entrypoint-screen')).toBeTruthy();
    expect(customElements.get('llm-key-msg-screen')).toBeTruthy();
    expect(customElements.get('error-banner')).toBeTruthy();
    expect(document.querySelector('#root > entrypoint-screen')).not.toBeNull();
    expect(document.querySelector('body > error-banner')).not.toBeNull();
  });

  it('rehydrates the lead before the first render on a hard reload of /workspace', async () => {
    sessionStorage.setItem('magic_link', 'tok');
    history.replaceState(null, '', '/workspace');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        json: () =>
          Promise.resolve({
            email: 'a@b.co',
            flow: 'guidebook',
            guidebook_id: 'gb-1',
            guidebook_name: 'Villa',
            guidebook_created_at: '2026-01-01T00:00:00Z',
          }),
      }),
    );
    const { bootstrap } = await import('./main');

    await bootstrap();

    expect(lead.value?.guidebook_id).toBe('gb-1');
    expect(document.querySelector('#root > llm-key-msg-screen')).not.toBeNull();
  });

  it('shows the error banner when the landing resolve fails with a non-auth error', async () => {
    history.replaceState(null, '', `${MAGIC_LINK_PATH}?ml=tok`);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    const { bootstrap } = await import('./main');

    await bootstrap();

    expect(bannerMessage.value).toBe('Something went wrong. Please try again.');
    // The token was consumed (URL stripped), not silently left dangling (US-03).
    expect(window.location.search).toBe('');
  });
});
