import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { bannerMessage, clearBanner, showBanner } from '../state/error-banner';
import { ErrorBanner } from './error-banner';

describe('error-banner', () => {
  let el: ErrorBanner;

  beforeEach(() => {
    clearBanner();
    el = new ErrorBanner();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
    clearBanner();
  });

  it('is hidden with no message', () => {
    expect(el.hidden).toBe(true);
  });

  it('shows the message text when set', () => {
    showBanner('Your link has expired.');
    expect(el.hidden).toBe(false);
    expect(el.querySelector('[data-message]')?.textContent).toBe('Your link has expired.');
  });

  it('dismiss button clears the banner', () => {
    showBanner('boom');
    el.querySelector<HTMLButtonElement>('[data-dismiss]')?.click();
    expect(bannerMessage.value).toBeNull();
    expect(el.hidden).toBe(true);
  });
});
