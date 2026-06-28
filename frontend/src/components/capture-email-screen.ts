import { postJson } from '../api/client';
import { ApplicationError, hasCode, messageFor } from '../api/errors';
import { captureFlow } from '../state/capture-flow';
import { EMAIL_MAX_LENGTH, isValidEmail } from '../utils/validation';

/**
 * Email capture (F-14 / §1.3.2 / §10.7).
 *
 * A trust-signalled form: email + a hidden honeypot (`name="website"`, §10.7 — bots fill it, humans
 * do not) → `POST /api/leads/capture` with `flow` from {@link captureFlow}. On success it swaps to the
 * "check your email" confirmation (the `email_sent` state, §1.3.1 — no separate route). Renders in
 * light DOM; self-registers as `<capture-email-screen>`.
 */
export class CaptureEmailScreen extends HTMLElement {
  private submitting = false;

  connectedCallback(): void {
    this.renderForm();
  }

  private renderForm(): void {
    this.innerHTML = `
      <section class="mx-auto flex max-w-md flex-col gap-5 px-4 py-12">
        <div class="flex flex-col gap-2">
          <h1 class="text-2xl font-semibold">Get your private link</h1>
          <p class="text-gray-600">We'll email you a magic link to your workspace. No password, no spam.</p>
        </div>
        <form data-form novalidate class="flex flex-col gap-4">
          <label class="flex flex-col gap-1 text-sm font-medium">
            Email
            <input data-email type="email" name="email" required autocomplete="email"
                   maxlength="${EMAIL_MAX_LENGTH}" inputmode="email"
                   class="rounded-md border border-gray-300 px-3 py-2 font-normal focus:border-blue-500 focus:outline-none" />
          </label>
          <input data-honeypot type="text" name="website" tabindex="-1" autocomplete="off"
                 aria-hidden="true" class="hidden" />
          <p data-error role="alert" class="hidden text-sm text-red-600"></p>
          <button data-submit type="submit"
                  class="rounded-md bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-60">
            Send
          </button>
        </form>
      </section>`;
    this.querySelector('[data-form]')?.addEventListener('submit', this.onSubmit);
  }

  private renderSent(): void {
    this.innerHTML = `
      <section class="mx-auto flex max-w-md flex-col gap-4 px-4 py-12 text-center">
        <h1 class="text-2xl font-semibold">Check your email</h1>
        <p class="text-gray-600">
          We sent a magic link to your inbox. Open it on this device to enter your workspace.
        </p>
      </section>`;
  }

  private setError(message: string | null): void {
    const el = this.querySelector('[data-error]');
    if (!el) {
      return;
    }
    el.textContent = message ?? '';
    el.classList.toggle('hidden', message === null);
  }

  private setSubmitting(value: boolean): void {
    this.submitting = value;
    const button = this.querySelector<HTMLButtonElement>('[data-submit]');
    if (button) {
      button.disabled = value;
      button.textContent = value ? 'Sending…' : 'Send';
    }
  }

  private readonly onSubmit = async (event: Event): Promise<void> => {
    event.preventDefault();
    if (this.submitting) {
      return;
    }
    const email = this.querySelector<HTMLInputElement>('[data-email]')?.value.trim() ?? '';
    const honeypot = this.querySelector<HTMLInputElement>('[data-honeypot]')?.value ?? '';
    if (!isValidEmail(email)) {
      this.setError('Please enter a valid email address.');
      return;
    }
    this.setError(null);
    this.setSubmitting(true);
    try {
      await postJson('/leads/capture', { email, flow: captureFlow.value, honeypot });
      this.renderSent();
    } catch (error) {
      this.setSubmitting(false);
      this.setError(this.messageForFailure(error));
    }
  };

  /** Map a submit failure to a user-facing line (§5.8 / §10.8); rate-limit shows the retry window. */
  private messageForFailure(error: unknown): string {
    if (!(error instanceof ApplicationError)) {
      return 'Something went wrong. Please try again.';
    }
    if (hasCode(error, 'ERR_RATE_LIMIT')) {
      return `${messageFor(error.code)} (retry in ${error.details.retry_after_s}s)`;
    }
    return messageFor(error.code);
  }
}

customElements.define('capture-email-screen', CaptureEmailScreen);
