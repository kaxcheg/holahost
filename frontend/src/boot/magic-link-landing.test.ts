import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { lead, magicLink } from '../state/session';
import { handleMagicLinkLanding } from './magic-link-landing';

function stubFetch(payload: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: () => Promise.resolve(payload) }));
}

beforeEach(() => {
  history.replaceState(null, '', '/');
  magicLink.value = null;
  lead.value = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('handleMagicLinkLanding', () => {
  it('returns "none" when there is no token', async () => {
    expect(await handleMagicLinkLanding()).toBe('none');
  });

  it('resolves a valid token, populates the session and strips the URL', async () => {
    history.replaceState(null, '', '/?ml=tok');
    const result = {
      email: 'a@b.co',
      flow: 'guidebook',
      guidebook_id: null,
      guidebook_name: null,
      guidebook_created_at: null,
    };
    stubFetch(result);

    expect(await handleMagicLinkLanding()).toBe('resolved');
    expect(magicLink.value).toBe('tok');
    expect(lead.value).toEqual(result);
    expect(window.location.search).toBe('');
  });

  it('returns "expired" and clears the session on ERR_INVALID_MAGIC_LINK', async () => {
    history.replaceState(null, '', '/?ml=bad');
    stubFetch({ error: { code: 'ERR_INVALID_MAGIC_LINK', message: 'expired', details: {} } });

    expect(await handleMagicLinkLanding()).toBe('expired');
    expect(magicLink.value).toBeNull();
    expect(lead.value).toBeNull();
  });
});
