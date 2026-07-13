import { signal } from '@preact/signals-core';

/**
 * Set to `true` on `ERR_SAMPLE_BUDGET_EXHAUSTED` (§10.8); disables the sample-flow forms until reset.
 */
export const sampleBudgetExhausted = signal(false);
