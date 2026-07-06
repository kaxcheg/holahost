import { beforeEach, describe, expect, it } from 'vitest';

import { lead, magicLink } from '../state/session';
import { navigate, resolveScreen } from './router';
import { isProtectedPath } from './routes';

beforeEach(() => {
  document.body.innerHTML = '<main id="root"></main>';
  history.replaceState(null, '', '/');
  magicLink.value = null;
  lead.value = null;
});

function mountedTag(): string | undefined {
  return document.querySelector('#root')?.firstElementChild?.tagName.toLowerCase();
}

describe('resolveScreen', () => {
  it('maps public paths to their screen', () => {
    expect(resolveScreen('/')).toEqual({ path: '/', tag: 'entrypoint-screen' });
    expect(resolveScreen('/sample-response').tag).toBe('sample-response-screen');
  });

  it('redirects unknown paths to the entrypoint', () => {
    expect(resolveScreen('/nope')).toEqual({ path: '/', tag: 'entrypoint-screen' });
  });

  it('guards protected paths when there is no magic link', () => {
    expect(resolveScreen('/workspace')).toEqual({ path: '/', tag: 'entrypoint-screen' });
  });

  it('resolves /workspace by guidebook presence when authenticated', () => {
    magicLink.value = 'tok';
    expect(resolveScreen('/workspace').tag).toBe('guidebook-screen');
    lead.value = {
      email: 'a@b.co',
      flow: 'guidebook',
      guidebook_id: 'gb-1',
      guidebook_name: 'Villa',
      guidebook_created_at: '2026-01-01T00:00:00Z',
    };
    expect(resolveScreen('/workspace').tag).toBe('llm-key-msg-screen');
  });
});

describe('isProtectedPath', () => {
  it('flags workspace paths as protected', () => {
    expect(isProtectedPath('/workspace')).toBe(true);
    expect(isProtectedPath('/workspace/upload')).toBe(true);
    expect(isProtectedPath('/workspace/template')).toBe(true);
  });

  it('flags public and unknown paths as not protected', () => {
    expect(isProtectedPath('/')).toBe(false);
    expect(isProtectedPath('/sample-response')).toBe(false);
    expect(isProtectedPath('/nope')).toBe(false);
  });
});

describe('navigate', () => {
  it('pushes state and mounts the screen', () => {
    navigate('/sample-response');
    expect(window.location.pathname).toBe('/sample-response');
    expect(mountedTag()).toBe('sample-response-screen');
  });

  it('mounts the entrypoint when navigating to a guarded path unauthenticated', () => {
    navigate('/workspace');
    expect(window.location.pathname).toBe('/');
    expect(mountedTag()).toBe('entrypoint-screen');
  });
});
