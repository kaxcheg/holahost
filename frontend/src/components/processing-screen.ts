/**
 * Intermediate processing indicator (F-18 / §11.3 loading state).
 *
 * A small reusable element shown by the one-shot operations (guidebook upload, template generate)
 * while their request is in flight: a spinner + a message from the `message` attribute. It is NOT a
 * routed screen (the state machine §1.3.1 has no processing state) — the owning screen swaps it in
 * for the duration of the `await` and swaps back to the result/error view. Light DOM (§11.5);
 * self-registers as `<processing-screen>`.
 */
export class ProcessingScreen extends HTMLElement {
  static readonly observedAttributes = ['message'];

  connectedCallback(): void {
    this.render();
  }

  attributeChangedCallback(): void {
    if (this.isConnected) {
      this.render();
    }
  }

  private render(): void {
    const message = this.getAttribute('message') ?? 'Working…';
    this.innerHTML = `
      <section class="mx-auto flex max-w-md flex-col items-center gap-4 px-4 py-16 text-center"
               role="status" aria-live="polite">
        <div class="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600"></div>
        <p data-message class="text-gray-600"></p>
      </section>`;
    const slot = this.querySelector('[data-message]');
    if (slot) {
      slot.textContent = message;
    }
  }
}

customElements.define('processing-screen', ProcessingScreen);
