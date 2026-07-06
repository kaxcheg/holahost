import { afterEach, describe, expect, it } from 'vitest';

import { sampleMessages } from './sample-messages';

describe('sampleMessages', () => {
  afterEach(() => {
    sampleMessages.value = null;
  });

  it('defaults to null (not yet loaded)', () => {
    expect(sampleMessages.value).toBeNull();
  });

  it('holds an ordered readonly list once set', () => {
    sampleMessages.value = ['a', 'b'];
    expect(sampleMessages.value).toEqual(['a', 'b']);
  });
});
