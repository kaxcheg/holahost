import { beforeEach, describe, expect, it } from 'vitest';

import { initSession, magicLink } from './session';

beforeEach(() => {
  sessionStorage.clear();
  magicLink.value = null;
});

describe('initSession', () => {
  it('restores magicLink from sessionStorage', () => {
    sessionStorage.setItem('magic_link', 'stored-token');
    initSession();
    expect(magicLink.value).toBe('stored-token');
  });

  it('mirrors magicLink changes back to sessionStorage', () => {
    initSession();
    magicLink.value = 'new-token';
    expect(sessionStorage.getItem('magic_link')).toBe('new-token');
    magicLink.value = null;
    expect(sessionStorage.getItem('magic_link')).toBeNull();
  });
});
