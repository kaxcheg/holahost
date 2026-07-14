import { effect } from '@preact/signals-core';

import { bannerMessage, clearBanner } from '../state/error-banner';

/**
 * Global, dismissible error banner (F-11 / §11.3).
 *
 * Subscribes to {@link bannerMessage}: renders a fixed top alert when the message is non-null, and
 * hides itself when `null`. Mounted once at startup (F-19), outside the router's `#root`, so it
 * survives screen changes. Renders in light DOM (no shadow root) so Tailwind utilities apply (§11.5).
 */
export class ErrorBanner extends HTMLElement {
  private dispose: (() => void) | undefined;

  connectedCallback(): void {
    this.addEventListener('click', this.onClick);
    this.dispose = effect(() => {
      this.render(bannerMessage.value);
    });
  }

  disconnectedCallback(): void {
    this.removeEventListener('click', this.onClick);
    this.dispose?.();
    this.dispose = undefined;
  }

  private readonly onClick = (event: MouseEvent): void => {
    if (event.target instanceof Element && event.target.closest('[data-dismiss]')) {
      clearBanner();
    }
  };

  private render(message: string | null): void {
    if (message === null) {
      this.hidden = true;
      this.replaceChildren();
      return;
    }
    this.hidden = false;
    this.innerHTML = `
      <div role="alert"
           class="fixed inset-x-0 top-0 z-50 flex items-center justify-between gap-4 bg-red-600 px-4 py-3 text-sm text-white shadow-md">
        <span data-message></span>
        <button type="button" data-dismiss aria-label="Dismiss"
                class="shrink-0 rounded px-2 text-lg leading-none hover:bg-red-700">&times;</button>
      </div>`;
    const slot = this.querySelector('[data-message]');
    if (slot) {
      slot.textContent = message;
    }
  }
}

customElements.define('error-banner', ErrorBanner);
