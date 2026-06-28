import { navigate } from '../router/router';
import { captureFlow } from '../state/capture-flow';

/**
 * Landing entry point (F-12 / §1.3.1 / §1.3.2): value proposition + the two entry actions —
 * **Try sample** (→ `/sample-response`) and **Use guidebook** (→ `/capture-email`, `flow='guidebook'`).
 *
 * Renders in light DOM (Tailwind utilities, §11.5); self-registers as `<entrypoint-screen>`.
 */
export class EntrypointScreen extends HTMLElement {
  connectedCallback(): void {
    this.innerHTML = `
      <section class="mx-auto flex max-w-xl flex-col gap-6 px-4 py-12 text-center">
        <h1 class="text-3xl font-semibold">Answer your guests in seconds</h1>
        <p class="text-gray-600">
          hola.host drafts replies to guest questions from your apartment guidebook.
          Try it on a sample, or use your own guidebook.
        </p>
        <div class="flex flex-col gap-3 sm:flex-row sm:justify-center">
          <button type="button" data-action="sample"
                  class="rounded-md bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700">
            Try sample
          </button>
          <button type="button" data-action="guidebook"
                  class="rounded-md border border-gray-300 px-5 py-2.5 font-medium hover:bg-gray-50">
            Use guidebook
          </button>
        </div>
      </section>`;
    this.addEventListener('click', this.onClick);
  }

  disconnectedCallback(): void {
    this.removeEventListener('click', this.onClick);
  }

  private readonly onClick = (event: MouseEvent): void => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const action = event.target.closest('[data-action]')?.getAttribute('data-action');
    if (action === 'sample') {
      navigate('/sample-response');
    } else if (action === 'guidebook') {
      captureFlow.value = 'guidebook';
      navigate('/capture-email');
    }
  };
}

customElements.define('entrypoint-screen', EntrypointScreen);
