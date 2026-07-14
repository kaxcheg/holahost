import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../router/router', () => ({ navigate: vi.fn() }));

import { navigate } from '../router/router';
import { captureFlow } from '../state/capture-flow';
import { EntrypointScreen } from './entrypoint-screen';

describe('entrypoint-screen', () => {
  let el: EntrypointScreen;

  beforeEach(() => {
    vi.mocked(navigate).mockReset();
    el = new EntrypointScreen();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
  });

  it('Try sample navigates to the sample flow', () => {
    el.querySelector<HTMLButtonElement>('[data-action="sample"]')?.click();
    expect(navigate).toHaveBeenCalledWith('/sample-response');
  });

  it('Use guidebook sets flow=guidebook and goes to capture', () => {
    captureFlow.value = 'sample';
    el.querySelector<HTMLButtonElement>('[data-action="guidebook"]')?.click();
    expect(captureFlow.value).toBe('guidebook');
    expect(navigate).toHaveBeenCalledWith('/capture-email');
  });
});
