import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({
  postJson: vi.fn(),
  withRetry: vi.fn((fn: () => Promise<unknown>) => fn()),
}));
vi.mock('../router/router', () => ({ navigate: vi.fn() }));

import { postJson } from '../api/client';
import { ApplicationError } from '../api/errors';
import { navigate } from '../router/router';
import { magicLink } from '../state/session';
import { LlmKeyMsgScreen } from './llm-key-msg-screen';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

function setValue(el: HTMLElement, selector: string, value: string): void {
  const field = el.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector);
  if (field) {
    field.value = value;
  }
}

describe('llm-key-msg-screen', () => {
  let el: LlmKeyMsgScreen;

  beforeEach(() => {
    vi.mocked(postJson).mockReset();
    vi.mocked(navigate).mockReset();
    magicLink.value = 'tok';
    el = new LlmKeyMsgScreen();
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
    el.querySelector<HTMLButtonElement>('[data-send]')?.click();
    await tick();
    expect(el.querySelector<HTMLInputElement>('[data-key]')?.value).toBe('');
    expect(el.querySelector('[data-error]')?.classList.contains('hidden')).toBe(false);
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
