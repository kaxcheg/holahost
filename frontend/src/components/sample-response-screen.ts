import { effect } from '@preact/signals-core';

import { postJson } from '../api/client';
import { ApplicationError, hasCode, messageFor } from '../api/errors';
import { navigate } from '../router/router';
import { captureFlow } from '../state/capture-flow';
import { sampleBudgetExhausted } from '../state/sample-budget';
import { sampleMessages } from '../state/sample-messages';
import { isValidGuestMessage, MAX_GUEST_MESSAGE_LENGTH } from '../utils/validation';

/** Published sample-messages list (§10.9); dev-served from docs/ by vite.config.ts. */
export const MESSAGES_URL = '/config/sample_messages.json';

/** Published sample guidebook (§10.9); key parity pinned by published-config-paths.test (C-11). */
export const SAMPLE_GUIDEBOOK_URL = '/config/sample_guidebook.md';

/** The list is a UX nicety: anything but non-empty strings degrades to an empty editable field. */
function isMessageList(value: unknown): value is readonly string[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((item) => typeof item === 'string' && item.trim().length > 0)
  );
}

/**
 * Sample flow v2 (F-20/F-21 / US-01 / §11.2).
 *
 * Fetches the ordered `SAMPLE_MESSAGES` list into {@link sampleMessages} (once, cached across
 * remounts), prefills the first item into an **editable** guest-message field, and sends the
 * actual field content to `POST /api/sample/generate`. Each reply is appended to the response
 * area **paired with the sent message**; after a reply the next list item is prefilled only when
 * the field still holds the sent prefill (manual input is never overwritten), and prefilling
 * stops once the list is exhausted while Send stays enabled. The download link points at the
 * published `/config/sample_guidebook.md` object. **Leave email** goes to `/capture-email` with
 * `flow='sample'`. When the global daily sample budget is exhausted ({@link sampleBudgetExhausted},
 * set here on `ERR_SAMPLE_BUDGET_EXHAUSTED`), Send is disabled. Renders in light DOM;
 * self-registers as `<sample-response-screen>`.
 */
export class SampleResponseScreen extends HTMLElement {
  private submitting = false;
  private prefillIndex = 0;
  private dispose: (() => void) | undefined;

  connectedCallback(): void {
    this.innerHTML = `
      <section class="mx-auto flex max-w-xl flex-col gap-5 px-4 py-12">
        <div class="flex flex-col gap-2">
          <h1 class="text-2xl font-semibold">Try it on a sample</h1>
          <p class="text-gray-600">Send a guest message — or write your own — and see the drafted reply.</p>
          <a href="${SAMPLE_GUIDEBOOK_URL}" download="sample_guidebook.md" data-sample-download
             class="text-sm text-blue-600 underline hover:text-blue-700">Download the sample guidebook</a>
        </div>
        <label class="flex flex-col gap-1 text-sm font-medium">
          Guest message
          <textarea data-message rows="2" maxlength="${MAX_GUEST_MESSAGE_LENGTH}"
                    class="resize-none rounded-md border border-gray-300 bg-white px-3 py-2 font-normal text-gray-900"></textarea>
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
    this.querySelector('[data-send]')?.addEventListener('click', this.onSend);
    this.querySelector('[data-leave-email]')?.addEventListener('click', this.onLeaveEmail);
    this.dispose = effect(() => {
      // Re-evaluates whenever the budget signal changes (also runs once on mount).
      this.updateSendState(sampleBudgetExhausted.value);
    });
    void this.loadMessages();
  }

  disconnectedCallback(): void {
    this.dispose?.();
    this.dispose = undefined;
  }

  private async loadMessages(): Promise<void> {
    if (sampleMessages.value === null) {
      try {
        const response = await fetch(MESSAGES_URL);
        if (!response.ok) {
          throw new Error(`sample messages ${response.status}`);
        }
        const parsed: unknown = await response.json();
        if (!isMessageList(parsed)) {
          throw new Error('sample messages: not a list of non-empty strings');
        }
        if (!this.isConnected) {
          return;
        }
        sampleMessages.value = parsed;
      } catch {
        // Degradation (US-01): keep the field empty and editable, Send stays functional.
        return;
      }
    }
    const field = this.querySelector<HTMLTextAreaElement>('[data-message]');
    const first = sampleMessages.value?.[0];
    if (field && first !== undefined && field.value === '') {
      this.prefillIndex = 0;
      field.value = first;
    }
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

  private appendPair(message: string, reply: string): void {
    const area = this.querySelector('[data-responses]');
    if (!area) {
      return;
    }
    const pair = document.createElement('div');
    pair.className =
      'flex flex-col gap-1 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm';
    const question = document.createElement('p');
    question.dataset.pairMessage = '';
    question.className = 'font-medium text-gray-500';
    question.textContent = message;
    const answer = document.createElement('p');
    answer.dataset.pairReply = '';
    answer.textContent = reply;
    pair.append(question, answer);
    area.append(pair);
  }

  private advancePrefill(field: HTMLTextAreaElement, sent: string, sentWasPrefill: boolean): void {
    const list = sampleMessages.value;
    if (list === null || !sentWasPrefill || field.value !== sent) {
      return;
    }
    const next = list[this.prefillIndex + 1];
    if (next === undefined) {
      return; // list exhausted: keep the sent text, Send stays enabled (US-01)
    }
    this.prefillIndex += 1;
    field.value = next;
  }

  private readonly onSend = async (): Promise<void> => {
    if (this.submitting || sampleBudgetExhausted.value) {
      return;
    }
    const field = this.querySelector<HTMLTextAreaElement>('[data-message]');
    if (!field) {
      return;
    }
    const message = field.value;
    if (!isValidGuestMessage(message)) {
      this.setError('Enter a guest message.');
      return;
    }
    this.setError(null);
    this.submitting = true;
    this.updateSendState(sampleBudgetExhausted.value);
    const sentWasPrefill = message === sampleMessages.value?.[this.prefillIndex];
    try {
      const result = await postJson('/sample/generate', { message });
      this.appendPair(message, result.response_text);
      this.advancePrefill(field, message, sentWasPrefill);
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
