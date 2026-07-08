import { postJson, withRetry } from '../api/client';
import { ApplicationError, hasCode, messageFor } from '../api/errors';
import { navigate } from '../router/router';
import { showBanner } from '../state/error-banner';
import { byokKey, guestMessage, type ResponsePair, responsePairs } from '../state/generate-fields';
import { clearSession, magicLink } from '../state/session';
import { isValidGuestMessage, MAX_GUEST_MESSAGE_LENGTH } from '../utils/validation';

/**
 * Generate screen (F-17 / F-25 / F-29 / §1.3.2 / §10.3).
 *
 * Host enters their BYOK Claude key (password input, in-memory only — never persisted, §10.3) and a
 * guest message; Send calls `POST /api/generate` (key as `X-Api-Key`, retryable upstream failures
 * backed off via {@link withRetry}) and appends each message → reply pair. The key, message, and
 * reply history live in module-scope signals (`state/generate-fields`, §11.2 / §11.4), so they
 * survive in-app navigation through the menu; a hard reload or tab close wipes them (US-06).
 * Inline submitting state (not a processing swap) so the inputs and prior replies survive repeated
 * sends. Light DOM; self-registers as `<generate-screen>`.
 */
export class GenerateScreen extends HTMLElement {
  private submitting = false;

  connectedCallback(): void {
    this.innerHTML = `
      <section class="mx-auto flex max-w-xl flex-col gap-5 px-4 py-10">
        <div class="flex flex-col gap-1">
          <h1 class="text-2xl font-semibold">Answer a guest</h1>
          <p class="text-gray-600">Your Claude key stays in this tab only — it's never stored or sent anywhere but Anthropic.</p>
        </div>
        <label class="flex flex-col gap-1 text-sm font-medium">
          Claude API key
          <input data-key type="password" autocomplete="off"
                 class="rounded-md border border-gray-300 px-3 py-2 font-normal focus:border-blue-500 focus:outline-none" />
        </label>
        <label class="flex flex-col gap-1 text-sm font-medium">
          Guest message
          <textarea data-message rows="3" maxlength="${MAX_GUEST_MESSAGE_LENGTH}"
                    class="resize-y rounded-md border border-gray-300 px-3 py-2 font-normal focus:border-blue-500 focus:outline-none"></textarea>
        </label>
        <button data-send type="button"
                class="self-start rounded-md bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-60">
          Send
        </button>
        <p data-error role="alert" class="hidden text-sm text-red-600"></p>
        <div data-responses class="flex flex-col gap-3"></div>
      </section>`;
    const key = this.querySelector<HTMLInputElement>('[data-key]');
    if (key) {
      key.value = byokKey.value;
    }
    const message = this.querySelector<HTMLTextAreaElement>('[data-message]');
    if (message) {
      message.value = guestMessage.value;
    }
    for (const pair of responsePairs.value) {
      this.appendPair(pair);
    }
    this.querySelector('[data-send]')?.addEventListener('click', this.onSend);
    this.addEventListener('input', this.onFieldInput);
  }

  disconnectedCallback(): void {
    this.querySelector('[data-send]')?.removeEventListener('click', this.onSend);
    this.removeEventListener('input', this.onFieldInput);
  }

  /** Mirror the inputs into the module-scope signals so they survive in-app navigation (US-06). */
  private readonly onFieldInput = (): void => {
    byokKey.value = this.querySelector<HTMLInputElement>('[data-key]')?.value ?? '';
    guestMessage.value = this.querySelector<HTMLTextAreaElement>('[data-message]')?.value ?? '';
  };

  private setError(message: string | null): void {
    const el = this.querySelector('[data-error]');
    if (el) {
      el.textContent = message ?? '';
      el.classList.toggle('hidden', message === null);
    }
  }

  private setSubmitting(value: boolean): void {
    this.submitting = value;
    const button = this.querySelector<HTMLButtonElement>('[data-send]');
    if (button) {
      button.disabled = value;
      button.textContent = value ? 'Sending…' : 'Send';
    }
  }

  private appendPair(pair: ResponsePair): void {
    const block = document.createElement('div');
    block.className = 'flex flex-col gap-1';
    const message = document.createElement('p');
    message.className = 'text-xs text-gray-500 whitespace-pre-wrap';
    message.textContent = pair.message;
    const reply = document.createElement('div');
    reply.className =
      'rounded-md border border-gray-200 bg-white px-3 py-2 text-sm whitespace-pre-wrap';
    reply.textContent = pair.response;
    block.append(message, reply);
    this.querySelector('[data-responses]')?.append(block);
  }

  private readonly onSend = async (): Promise<void> => {
    if (this.submitting) {
      return;
    }
    const key = this.querySelector<HTMLInputElement>('[data-key]')?.value.trim() ?? '';
    const message = this.querySelector<HTMLTextAreaElement>('[data-message]')?.value ?? '';
    if (!key) {
      this.setError('Enter your Claude API key.');
      return;
    }
    if (!isValidGuestMessage(message)) {
      this.setError('Enter a guest message.');
      return;
    }
    this.setError(null);
    this.setSubmitting(true);
    try {
      const result = await withRetry(() =>
        postJson('/generate', { message }, { magicLink: magicLink.value ?? undefined, byok: key }),
      );
      const pair: ResponsePair = { message, response: result.response_text };
      responsePairs.value = [...responsePairs.value, pair];
      this.appendPair(pair);
    } catch (error) {
      this.handleError(error);
    } finally {
      this.setSubmitting(false);
    }
  };

  private handleError(error: unknown): void {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      this.setError('The request timed out. Please try again.');
      return;
    }
    if (!(error instanceof ApplicationError)) {
      this.setError('Something went wrong. Please try again.');
      return;
    }
    if (hasCode(error, 'ERR_INVALID_MAGIC_LINK')) {
      clearSession();
      showBanner(messageFor(error.code));
      navigate('/');
      return;
    }
    if (hasCode(error, 'ERR_INVALID_API_KEY')) {
      byokKey.value = '';
      const keyInput = this.querySelector<HTMLInputElement>('[data-key]');
      if (keyInput) {
        keyInput.value = '';
        keyInput.focus();
      }
      this.setError(messageFor(error.code));
      return;
    }
    if (hasCode(error, 'ERR_NO_GUIDEBOOK')) {
      showBanner(messageFor(error.code));
      navigate('/guidebook');
      return;
    }
    if (hasCode(error, 'ERR_RATE_LIMIT')) {
      this.setError(`${messageFor(error.code)} (retry in ${error.details.retry_after_s}s)`);
      return;
    }
    this.setError(messageFor(error.code));
  }
}

customElements.define('generate-screen', GenerateScreen);
