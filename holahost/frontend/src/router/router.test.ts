import { beforeEach, describe, expect, it } from 'vitest';

import { currentPath } from '../state/route';
import { magicLink } from '../state/session';
import { navigate, resolveScreen } from './router';
import { isProtectedPath } from './routes';

beforeEach(() => {
  document.body.innerHTML = '<main id="root"></main>';
  history.replaceState(null, '', '/');
  magicLink.value = null;
  currentPath.value = '/';
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
    expect(resolveScreen('/guidebook')).toEqual({ path: '/', tag: 'entrypoint-screen' });
  });

  it('resolves each screen path to its tag when authenticated', () => {
    magicLink.value = 'tok';
    expect(resolveScreen('/guidebook').tag).toBe('guidebook-screen');
    expect(resolveScreen('/template').tag).toBe('template-screen');
    expect(resolveScreen('/generate').tag).toBe('generate-screen');
  });

  it('normalizes a trailing slash to the canonical path', () => {
    magicLink.value = 'tok';
    expect(resolveScreen('/guidebook/')).toEqual({ path: '/guidebook', tag: 'guidebook-screen' });
  });

  it('falls back to the entrypoint on the retired /workspace paths', () => {
    magicLink.value = 'tok';
    expect(resolveScreen('/workspace').path).toBe('/');
    expect(resolveScreen('/workspace/upload').path).toBe('/');
    expect(resolveScreen('/workspace/template').path).toBe('/');
  });
});

describe('isProtectedPath', () => {
  it('flags screen paths as protected, trailing-slash tolerant', () => {
    for (const path of ['/guidebook', '/template', '/generate', '/guidebook/']) {
      expect(isProtectedPath(path)).toBe(true);
    }
  });

  it('flags public, unknown, and retired paths as not protected', () => {
    expect(isProtectedPath('/')).toBe(false);
    expect(isProtectedPath('/sample-response')).toBe(false);
    expect(isProtectedPath('/nope')).toBe(false);
    expect(isProtectedPath('/workspace')).toBe(false);
  });
});

describe('navigate', () => {
  it('pushes state and mounts the screen', () => {
    navigate('/sample-response');
    expect(window.location.pathname).toBe('/sample-response');
    expect(mountedTag()).toBe('sample-response-screen');
  });

  it('pushes the canonical path for a trailing-slash request', () => {
    magicLink.value = 'tok';
    navigate('/guidebook/');
    expect(window.location.pathname).toBe('/guidebook');
    expect(mountedTag()).toBe('guidebook-screen');
  });

  it('mounts the entrypoint when navigating to a guarded path unauthenticated', () => {
    navigate('/guidebook');
    expect(window.location.pathname).toBe('/');
    expect(mountedTag()).toBe('entrypoint-screen');
  });

  it('tracks the mounted path in currentPath', () => {
    magicLink.value = 'tok';
    navigate('/generate');
    expect(currentPath.value).toBe('/generate');
    navigate('/nope');
    expect(currentPath.value).toBe('/');
  });
});
