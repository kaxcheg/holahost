import { beforeEach, describe, expect, it } from 'vitest';

import { byokKey, guestMessage, responsePairs } from './generate-fields';

describe('generate-fields', () => {
  beforeEach(() => {
    byokKey.value = '';
    guestMessage.value = '';
    responsePairs.value = [];
  });

  it('exposes empty in-memory defaults', () => {
    expect(byokKey.value).toBe('');
    expect(guestMessage.value).toBe('');
    expect(responsePairs.value).toEqual([]);
  });
});
