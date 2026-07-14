import { afterEach, describe, expect, it } from 'vitest';

import { sampleBudgetExhausted } from './sample-budget';

afterEach(() => {
  sampleBudgetExhausted.value = false;
});

describe('sampleBudgetExhausted', () => {
  it('defaults to false and is settable', () => {
    expect(sampleBudgetExhausted.value).toBe(false);
    sampleBudgetExhausted.value = true;
    expect(sampleBudgetExhausted.value).toBe(true);
  });
});
