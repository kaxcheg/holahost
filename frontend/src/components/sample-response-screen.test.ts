import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ postJson: vi.fn() }));
vi.mock('../router/router', () => ({ navigate: vi.fn() }));

import { postJson } from '../api/client';
import { ApplicationError } from '../api/errors';
import { navigate } from '../router/router';
import { captureFlow } from '../state/capture-flow';
import { sampleBudgetExhausted } from '../state/sample-budget';
import { SampleResponseScreen } from './sample-response-screen';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe('sample-response-screen', () => {
  let el: SampleResponseScreen;

  beforeEach(() => {
    vi.mocked(postJson).mockReset();
    vi.mocked(navigate).mockReset();
    sampleBudgetExhausted.value = false;
    el = new SampleResponseScreen();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
    sampleBudgetExhausted.value = false;
  });

  it('Send calls the sample endpoint and appends the reply', async () => {
    vi.mocked(postJson).mockResolvedValue({ response_text: 'Check-in is at 3pm.' });
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(postJson).toHaveBeenCalledWith('/sample/generate', { message: expect.any(String) });
    expect(el.querySelector('[data-responses]')?.textContent).toContain('Check-in is at 3pm.');
  });

  it('disables Send when the sample budget is exhausted', () => {
    sampleBudgetExhausted.value = true;
    expect(el.querySelector<HTMLButtonElement>('[data-send]')?.disabled).toBe(true);
  });

  it('sets the budget signal on ERR_SAMPLE_BUDGET_EXHAUSTED', async () => {
    vi.mocked(postJson).mockRejectedValue(
      new ApplicationError('ERR_SAMPLE_BUDGET_EXHAUSTED', 'x', {
        reset_at: '2026-06-29T00:00:00Z',
      }),
    );
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(sampleBudgetExhausted.value).toBe(true);
  });

  it('Leave email sets flow=sample and navigates to capture', () => {
    el.querySelector<HTMLButtonElement>('[data-leave-email]')?.click();
    expect(captureFlow.value).toBe('sample');
    expect(navigate).toHaveBeenCalledWith('/capture-email');
  });
});
