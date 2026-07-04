import { describe, expect, it } from 'vitest';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe('main bootstrap', () => {
  it('registers the screens and mounts the entrypoint + error banner', async () => {
    document.body.innerHTML = '<main id="root"></main>';
    // The test URL is not the magic-link landing path (and has no `?ml=`) → landing is a no-op; the
    // router renders the entrypoint.
    await import('./main');
    await tick();

    expect(customElements.get('entrypoint-screen')).toBeTruthy();
    expect(customElements.get('llm-key-msg-screen')).toBeTruthy();
    expect(customElements.get('error-banner')).toBeTruthy();
    expect(document.querySelector('#root > entrypoint-screen')).not.toBeNull();
    expect(document.querySelector('body > error-banner')).not.toBeNull();
  });
});
