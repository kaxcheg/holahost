import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ProcessingScreen } from './processing-screen';

describe('processing-screen', () => {
  let el: ProcessingScreen;

  afterEach(() => {
    el?.remove();
  });

  beforeEach(() => {
    el = new ProcessingScreen();
  });

  it('shows the message from the attribute', () => {
    el.setAttribute('message', 'Uploading…');
    document.body.append(el);
    expect(el.querySelector('[data-message]')?.textContent).toBe('Uploading…');
    expect(el.querySelector('[role="status"]')).not.toBeNull();
  });

  it('falls back to a default message', () => {
    document.body.append(el);
    expect(el.querySelector('[data-message]')?.textContent).toBe('Working…');
  });
});
