import { postJson, withRetry } from '../api/client';
import { ApplicationError, hasCode, messageFor } from '../api/errors';
import { navigate } from '../router/router';
import { showBanner } from '../state/error-banner';
import { clearSession, magicLink } from '../state/session';
import { isValidGuestMessage, MAX_GUEST_MESSAGE_LENGTH } from '../utils/validation';

/**
 * Answer screen (F-17 / §1.3.2 / §10.3).
 *
 * Host enters their BYOK Claude key (password input, in-memory only — never persisted, §10.3) and a
 * guest message; Send calls `POST /api/generate` (key as `X-Api-Key`, retryable upstream failures
 * backed off via {@link withRetry}) and appends each reply. The key and message inputs persist in the
 * element while mounted. Inline submitting state (not a processing swap) so the inputs and prior
 * replies survive repeated sends. Light DOM; self-registers as `<llm-key-msg-screen>`.
 */
export class LlmKeyMsgScreen extends HTMLElement {
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
    this.querySelector('[data-send]')?.addEventListener('click', this.onSend);
  }

  disconnectedCallback(): void {
    this.querySelector('[data-send]')?.removeEventListener('click', this.onSend);
  }

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

  private appendResponse(text: string): void {
    const block = document.createElement('div');
    block.className =
      'rounded-md border border-gray-200 bg-white px-3 py-2 text-sm whitespace-pre-wrap';
    block.textContent = text;
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
      this.appendResponse(result.response_text);
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
      navigate('/workspace/upload');
      return;
    }
    if (hasCode(error, 'ERR_RATE_LIMIT')) {
      this.setError(`${messageFor(error.code)} (retry in ${error.details.retry_after_s}s)`);
      return;
    }
    this.setError(messageFor(error.code));
  }
}

customElements.define('llm-key-msg-screen', LlmKeyMsgScreen);
