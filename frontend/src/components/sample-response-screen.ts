import { effect } from '@preact/signals-core';

import { postJson } from '../api/client';
import { ApplicationError, hasCode, messageFor } from '../api/errors';
import { navigate } from '../router/router';
import { captureFlow } from '../state/capture-flow';
import { sampleBudgetExhausted } from '../state/sample-budget';

/** Preloaded guest question shown read-only in the sample flow (§1.3.2 / §6.1). */
const SAMPLE_MESSAGE = 'Hi! What time is check-in, and is there parking nearby?';

/**
 * Sample flow (F-13 / §1.3.2 / §10.2).
 *
 * Shows a download link to a sample guidebook, a read-only preloaded guest message, and a Send button
 * that calls `POST /api/sample/generate` and appends each reply to the response area. **Leave email**
 * goes to `/capture-email` with `flow='sample'`. When the global daily sample budget is exhausted
 * ({@link sampleBudgetExhausted}, set here on `ERR_SAMPLE_BUDGET_EXHAUSTED`), Send is disabled.
 * Renders in light DOM; self-registers as `<sample-response-screen>`.
 */
export class SampleResponseScreen extends HTMLElement {
  private submitting = false;
  private dispose: (() => void) | undefined;

  connectedCallback(): void {
    this.innerHTML = `
      <section class="mx-auto flex max-w-xl flex-col gap-5 px-4 py-12">
        <div class="flex flex-col gap-2">
          <h1 class="text-2xl font-semibold">Try it on a sample</h1>
          <p class="text-gray-600">Send the sample guest message and see the drafted reply.</p>
          <a href="/sample-guidebook.pdf" download data-sample-download
             class="text-sm text-blue-600 underline hover:text-blue-700">Download the sample guidebook</a>
        </div>
        <label class="flex flex-col gap-1 text-sm font-medium">
          Guest message
          <textarea data-message readonly rows="2"
                    class="resize-none rounded-md border border-gray-300 bg-gray-50 px-3 py-2 font-normal text-gray-700"></textarea>
        </label>
        <button data-send type="button"
                class="self-start rounded-md bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-60">
          Send
        </button>
        <p data-error role="alert" class="hidden text-sm text-red-600"></p>
        <div data-responses class="flex flex-col gap-3"></div>
        <button data-leave-email type="button"
                class="self-start text-sm text-blue-600 underline hover:text-blue-700">
          Leave your email to use your own guidebook
        </button>
      </section>`;
    const messageField = this.querySelector<HTMLTextAreaElement>('[data-message]');
    if (messageField) {
      messageField.value = SAMPLE_MESSAGE;
    }
    this.querySelector('[data-send]')?.addEventListener('click', this.onSend);
    this.querySelector('[data-leave-email]')?.addEventListener('click', this.onLeaveEmail);
    this.dispose = effect(() => {
      // Re-evaluates whenever the budget signal changes (also runs once on mount).
      this.updateSendState(sampleBudgetExhausted.value);
    });
  }

  disconnectedCallback(): void {
    this.dispose?.();
    this.dispose = undefined;
  }

  private updateSendState(exhausted: boolean): void {
    const button = this.querySelector<HTMLButtonElement>('[data-send]');
    if (button) {
      button.disabled = exhausted || this.submitting;
    }
  }

  private setError(message: string | null): void {
    const el = this.querySelector('[data-error]');
    if (!el) {
      return;
    }
    el.textContent = message ?? '';
    el.classList.toggle('hidden', message === null);
  }

  private appendResponse(text: string): void {
    const block = document.createElement('div');
    block.className = 'rounded-md border border-gray-200 bg-white px-3 py-2 text-sm';
    block.textContent = text;
    this.querySelector('[data-responses]')?.append(block);
  }

  private readonly onSend = async (): Promise<void> => {
    if (this.submitting || sampleBudgetExhausted.value) {
      return;
    }
    this.setError(null);
    this.submitting = true;
    this.updateSendState(sampleBudgetExhausted.value);
    try {
      const result = await postJson('/sample/generate', { message: SAMPLE_MESSAGE });
      this.appendResponse(result.response_text);
    } catch (error) {
      this.handleError(error);
    } finally {
      this.submitting = false;
      this.updateSendState(sampleBudgetExhausted.value);
    }
  };

  private handleError(error: unknown): void {
    if (!(error instanceof ApplicationError)) {
      this.setError('Something went wrong. Please try again.');
      return;
    }
    if (hasCode(error, 'ERR_SAMPLE_BUDGET_EXHAUSTED')) {
      sampleBudgetExhausted.value = true;
      this.setError(messageFor(error.code));
      return;
    }
    if (hasCode(error, 'ERR_RATE_LIMIT')) {
      this.setError(`${messageFor(error.code)} (retry in ${error.details.retry_after_s}s)`);
      return;
    }
    this.setError(messageFor(error.code));
  }

  private readonly onLeaveEmail = (): void => {
    captureFlow.value = 'sample';
    navigate('/capture-email');
  };
}

customElements.define('sample-response-screen', SampleResponseScreen);
