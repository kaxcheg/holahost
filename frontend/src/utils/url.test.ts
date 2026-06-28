import { describe, expect, it } from 'vitest';

import { extractMagicLink, stripQuery } from './url';

describe('extractMagicLink', () => {
  it('returns the token when present', () => {
    expect(extractMagicLink('?ml=abc123', 'ml')).toBe('abc123');
  });

  it('returns null when the param is absent', () => {
    expect(extractMagicLink('?other=1', 'ml')).toBeNull();
  });

  it('returns null for an empty value', () => {
    expect(extractMagicLink('?ml=', 'ml')).toBeNull();
  });

  it('returns null for an empty query', () => {
    expect(extractMagicLink('', 'ml')).toBeNull();
  });
});

describe('stripQuery', () => {
  it('removes the query string but keeps the path', () => {
    history.replaceState(null, '', '/workspace?ml=secret');
    stripQuery();
    expect(window.location.search).toBe('');
    expect(window.location.pathname).toBe('/workspace');
  });
});
