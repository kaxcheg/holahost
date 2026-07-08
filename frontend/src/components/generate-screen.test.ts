import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({
  postJson: vi.fn(),
  withRetry: vi.fn((fn: () => Promise<unknown>) => fn()),
}));
vi.mock('../router/router', () => ({ navigate: vi.fn() }));

import { postJson } from '../api/client';
import { ApplicationError } from '../api/errors';
import { navigate } from '../router/router';
import { byokKey, guestMessage, responsePairs } from '../state/generate-fields';
import { magicLink } from '../state/session';
import { GenerateScreen } from './generate-screen';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

function setValue(el: HTMLElement, selector: string, value: string): void {
  const field = el.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector);
  if (field) {
    field.value = value;
  }
}

describe('generate-screen', () => {
  let el: GenerateScreen;

  beforeEach(() => {
    vi.mocked(postJson).mockReset();
    vi.mocked(navigate).mockReset();
    magicLink.value = 'tok';
    byokKey.value = '';
    guestMessage.value = '';
    responsePairs.value = [];
    el = new GenerateScreen();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
    magicLink.value = null;
  });

  it('requires a key before calling the API', () => {
    setValue(el, '[data-message]', 'How do I check in?');
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    expect(postJson).not.toHaveBeenCalled();
    expect(el.querySelector('[data-error]')?.textContent).toMatch(/key/i);
  });

  it('sends the message with the BYOK key and appends the reply', async () => {
    vi.mocked(postJson).mockResolvedValue({ response_text: 'Check-in is at 3pm.' });
    setValue(el, '[data-key]', 'sk-test');
    setValue(el, '[data-message]', 'When is check-in?');
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(postJson).toHaveBeenCalledWith(
      '/generate',
      { message: 'When is check-in?' },
      expect.objectContaining({ magicLink: 'tok', byok: 'sk-test' }),
    );
    expect(el.querySelector('[data-responses]')?.textContent).toContain('Check-in is at 3pm.');
  });

  it('clears the key on ERR_INVALID_API_KEY', async () => {
    vi.mocked(postJson).mockRejectedValue(new ApplicationError('ERR_INVALID_API_KEY', 'x', {}));
    setValue(el, '[data-key]', 'sk-bad');
    setValue(el, '[data-message]', 'hi there');
    byokKey.value = 'sk-bad';
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(el.querySelector<HTMLInputElement>('[data-key]')?.value).toBe('');
    expect(byokKey.value).toBe('');
    expect(el.querySelector('[data-error]')?.classList.contains('hidden')).toBe(false);
  });

  it('restores fields and history from the signals on mount', () => {
    byokKey.value = 'sk-test';
    guestMessage.value = 'Hi';
    responsePairs.value = [{ message: 'Hi', response: 'Check-in is at 3pm.' }];
    el.remove();
    el = new GenerateScreen();
    document.body.append(el);
    expect(el.querySelector<HTMLInputElement>('[data-key]')?.value).toBe('sk-test');
    expect(el.querySelector<HTMLTextAreaElement>('[data-message]')?.value).toBe('Hi');
    expect(el.querySelector('[data-responses]')?.textContent).toContain('Check-in is at 3pm.');
  });

  it('mirrors typed values into the signals', () => {
    const key = el.querySelector<HTMLInputElement>('[data-key]');
    if (key) {
      key.value = 'sk-live';
      key.dispatchEvent(new Event('input', { bubbles: true }));
    }
    expect(byokKey.value).toBe('sk-live');
  });

  it('appends the sent pair to responsePairs on success', async () => {
    vi.mocked(postJson).mockResolvedValue({ response_text: 'Reply' });
    setValue(el, '[data-key]', 'sk-test');
    setValue(el, '[data-message]', 'Hi');
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(responsePairs.value).toEqual([{ message: 'Hi', response: 'Reply' }]);
  });

  it('sends the host to the guidebook screen on ERR_NO_GUIDEBOOK', async () => {
    vi.mocked(postJson).mockRejectedValue(new ApplicationError('ERR_NO_GUIDEBOOK', 'x', {}));
    setValue(el, '[data-key]', 'sk-test');
    setValue(el, '[data-message]', 'hi there');
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(navigate).toHaveBeenCalledWith('/guidebook');
  });

  it('clears the session and redirects on ERR_INVALID_MAGIC_LINK', async () => {
    vi.mocked(postJson).mockRejectedValue(new ApplicationError('ERR_INVALID_MAGIC_LINK', 'x', {}));
    setValue(el, '[data-key]', 'sk-test');
    setValue(el, '[data-message]', 'hi there');
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(magicLink.value).toBeNull();
    expect(navigate).toHaveBeenCalledWith('/');
  });
});
