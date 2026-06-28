import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ postJson: vi.fn() }));

import { postJson } from '../api/client';
import { ApplicationError } from '../api/errors';
import { captureFlow } from '../state/capture-flow';
import { CaptureEmailScreen } from './capture-email-screen';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

function submit(el: HTMLElement): void {
  el.querySelector('[data-form]')?.dispatchEvent(new Event('submit', { cancelable: true }));
}

function setEmail(el: HTMLElement, value: string): void {
  const input = el.querySelector<HTMLInputElement>('[data-email]');
  if (input) {
    input.value = value;
  }
}

describe('capture-email-screen', () => {
  let el: CaptureEmailScreen;

  beforeEach(() => {
    vi.mocked(postJson).mockReset();
    captureFlow.value = 'guidebook';
    el = new CaptureEmailScreen();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
  });

  it('posts a valid email with flow + empty honeypot, then shows the confirmation', async () => {
    vi.mocked(postJson).mockResolvedValue({ status: 'sent' });
    setEmail(el, 'host@example.com');
    captureFlow.value = 'sample';
    submit(el);
    await tick();
    expect(postJson).toHaveBeenCalledWith('/leads/capture', {
      email: 'host@example.com',
      flow: 'sample',
      honeypot: '',
    });
    expect(el.textContent).toContain('Check your email');
  });

  it('rejects an invalid email without calling the API', () => {
    setEmail(el, 'not-an-email');
    submit(el);
    expect(postJson).not.toHaveBeenCalled();
    expect(el.querySelector('[data-error]')?.textContent).toMatch(/valid email/i);
  });

  it('shows the mapped message on an application error', async () => {
    vi.mocked(postJson).mockRejectedValue(
      new ApplicationError('ERR_UPSTREAM_EMAIL', 'x', { retryable: true }),
    );
    setEmail(el, 'host@example.com');
    submit(el);
    await tick();
    expect(el.querySelector('[data-error]')?.classList.contains('hidden')).toBe(false);
    expect(el.textContent).not.toContain('Check your email');
    const button = el.querySelector<HTMLButtonElement>('[data-submit]');
    expect(button?.disabled).toBe(false);
    expect(button?.textContent).toBe('Send');
  });
});
