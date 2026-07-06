import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ get: vi.fn() }));

import { get } from '../api/client';
import { ApplicationError } from '../api/errors';
import { bannerMessage, clearBanner } from '../state/error-banner';
import { lead, magicLink } from '../state/session';
import { rehydrateWorkspaceLead } from './workspace-rehydrate';

const LEAD = {
  email: 'a@b.co',
  flow: 'guidebook',
  guidebook_id: 'gb-1',
  guidebook_name: 'Villa',
  guidebook_created_at: '2026-01-01T00:00:00Z',
};

describe('rehydrateWorkspaceLead', () => {
  beforeEach(() => {
    vi.mocked(get).mockReset();
    magicLink.value = null;
    lead.value = null;
    clearBanner();
    history.replaceState(null, '', '/workspace');
  });

  afterEach(() => {
    history.replaceState(null, '', '/');
  });

  it('rehydrates the lead from /magic-link/resolve', async () => {
    magicLink.value = 'tok';
    vi.mocked(get).mockResolvedValue(LEAD);

    await rehydrateWorkspaceLead();

    expect(get).toHaveBeenCalledWith('/magic-link/resolve', { magicLink: 'tok' });
    expect(lead.value).toEqual(LEAD);
    expect(bannerMessage.value).toBeNull();
  });

  it('clears the session and shows a banner on ERR_INVALID_MAGIC_LINK', async () => {
    magicLink.value = 'tok';
    vi.mocked(get).mockRejectedValue(new ApplicationError('ERR_INVALID_MAGIC_LINK', 'expired', {}));

    await rehydrateWorkspaceLead();

    expect(magicLink.value).toBeNull();
    expect(lead.value).toBeNull();
    expect(bannerMessage.value).not.toBeNull();
  });

  it('keeps the session but falls back to the entrypoint on a network failure', async () => {
    magicLink.value = 'tok';
    vi.mocked(get).mockRejectedValue(new TypeError('offline'));

    await rehydrateWorkspaceLead();

    expect(magicLink.value).toBe('tok');
    expect(lead.value).toBeNull();
    expect(window.location.pathname).toBe('/');
    expect(bannerMessage.value).not.toBeNull();
  });

  it('is a no-op without a stored magic link', async () => {
    await rehydrateWorkspaceLead();

    expect(get).not.toHaveBeenCalled();
  });
});
