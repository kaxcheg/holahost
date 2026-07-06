import { postForm, UPLOAD_TIMEOUT_MS } from '../api/client';
import { ApplicationError, hasCode, messageFor } from '../api/errors';
import { navigate } from '../router/router';
import { showBanner } from '../state/error-banner';
import { clearSession, lead, magicLink, templateSchema } from '../state/session';

/** A guidebook-template form field (shape of each entry in `/config/template_schema.json`, §10.6). */
interface TemplateField {
  readonly name: string;
  readonly label: string;
  readonly required: boolean;
  readonly max_length: number;
  readonly hint: string;
}

const SCHEMA_URL = '/config/template_schema.json';
const NAME_FIELD = 'property_name';

/**
 * Template-form workspace (F-16 / §10.6).
 *
 * Fetches the field schema from `/config/template_schema.json` (cached in the `templateSchema`
 * signal), renders a dynamic form, and on Generate renders the filled fields to plain text
 * (`<label>: <value>` blocks) and uploads it via `POST /api/ingest/upload` (`text/plain`,
 * `name = property_name`). The backend runs the same ingest pipeline as a file upload. On success it
 * updates `lead` and goes to the answer screen. Light DOM; self-registers as `<template-screen>`.
 */
export class TemplateScreen extends HTMLElement {
  connectedCallback(): void {
    this.addEventListener('click', this.onClick);
    void this.load();
  }

  disconnectedCallback(): void {
    this.removeEventListener('click', this.onClick);
  }

  private async load(): Promise<void> {
    const cached = templateSchema.value as readonly TemplateField[] | null;
    if (cached) {
      this.renderForm(cached);
      return;
    }
    this.innerHTML = '<processing-screen message="Loading the template…"></processing-screen>';
    try {
      const response = await fetch(SCHEMA_URL);
      if (!response.ok) {
        throw new Error(`schema ${response.status}`);
      }
      const parsed: unknown = await response.json();
      if (!Array.isArray(parsed)) {
        // An SPA fallback or a misshapen publish must not poison the templateSchema cache —
        // a cached non-array would crash renderForm on every remount (US-05, F-24).
        throw new Error('schema: not an array');
      }
      const fields = parsed as readonly TemplateField[];
      if (!this.isConnected) {
        return;
      }
      templateSchema.value = fields;
      this.renderForm(fields);
    } catch {
      if (this.isConnected) {
        this.renderLoadError();
      }
    }
  }

  private renderForm(fields: readonly TemplateField[]): void {
    // data-field / maxlength carry controlled identifiers + numbers; label/hint text (freeform) is set
    // via textContent below, never interpolated into innerHTML.
    const rows = fields
      .map(
        (f) => `
        <label class="flex flex-col gap-1 text-sm font-medium">
          <span><span data-label></span>${f.required ? ' <span class="text-red-600">*</span>' : ''}</span>
          <textarea data-field="${f.name}" rows="2" maxlength="${f.max_length}"
                    ${f.required ? 'data-required' : ''}
                    class="resize-y rounded-md border border-gray-300 px-3 py-2 font-normal focus:border-blue-500 focus:outline-none"></textarea>
          <span data-hint class="font-normal text-gray-400"></span>
        </label>`,
      )
      .join('');
    this.innerHTML = `
      <section class="mx-auto flex max-w-2xl flex-col gap-5 px-4 py-10">
        <div class="flex flex-col gap-1">
          <h1 class="text-2xl font-semibold">Generate from a template</h1>
          <p class="text-gray-600">Fill in what applies — required fields are marked *.</p>
        </div>
        <form data-form novalidate class="flex flex-col gap-4">${rows}
          <p data-error role="alert" class="hidden text-sm text-red-600"></p>
          <button data-action="generate" type="submit"
                  class="self-start rounded-md bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-60">
            Generate
          </button>
        </form>
      </section>`;
    // Label + hint text set via textContent (avoid interpolating schema strings into innerHTML).
    const labelSlots = this.querySelectorAll('[data-label]');
    const hintSlots = this.querySelectorAll('[data-hint]');
    fields.forEach((f, i) => {
      const labelSlot = labelSlots[i];
      if (labelSlot) {
        labelSlot.textContent = f.label;
      }
      const hintSlot = hintSlots[i];
      if (hintSlot) {
        hintSlot.textContent = f.hint;
      }
    });
    this.querySelector('[data-form]')?.addEventListener('submit', this.onSubmit);
  }

  private renderLoadError(): void {
    this.innerHTML = `
      <section class="mx-auto flex max-w-md flex-col gap-4 px-4 py-12 text-center">
        <p data-load-error role="alert" class="text-sm text-red-600">Couldn't load the template form. Please try again later.</p>
        <button data-action="back" type="button"
                class="self-center rounded-md border border-gray-300 px-5 py-2.5 font-medium hover:bg-gray-50">
          Back
        </button>
      </section>`;
  }

  private setError(message: string | null): void {
    const el = this.querySelector('[data-error]');
    if (el) {
      el.textContent = message ?? '';
      el.classList.toggle('hidden', message === null);
    }
  }

  private setSubmitting(value: boolean): void {
    // Inline busy state (not a processing-screen swap) so the filled form survives a failed submit.
    const button = this.querySelector<HTMLButtonElement>('[data-action="generate"]');
    if (button) {
      button.disabled = value;
      button.textContent = value ? 'Generating…' : 'Generate';
    }
  }

  private collect(): { name: string; text: string } | null {
    const fields = this.querySelectorAll<HTMLTextAreaElement>('[data-field]');
    const blocks: string[] = [];
    let name = '';
    let missingRequired = false;
    for (const field of fields) {
      const key = field.getAttribute('data-field') ?? '';
      const value = field.value.trim();
      if (field.hasAttribute('data-required') && !value) {
        missingRequired = true;
      }
      if (key === NAME_FIELD) {
        name = value;
      }
      if (value) {
        const label = field.closest('label')?.querySelector('span')?.textContent ?? key;
        blocks.push(`${label.replace(/\s*\*$/, '')}: ${value}`);
      }
    }
    if (missingRequired || !name) {
      this.setError('Please fill in all required fields (marked *).');
      return null;
    }
    return { name, text: blocks.join('\n\n') };
  }

  private readonly onClick = (event: MouseEvent): void => {
    if (event.target instanceof Element && event.target.closest('[data-action="back"]')) {
      navigate('/workspace/upload');
    }
  };

  private readonly onSubmit = async (event: Event): Promise<void> => {
    event.preventDefault();
    const collected = this.collect();
    if (!collected) {
      return;
    }
    const form = new FormData();
    form.append('name', collected.name);
    form.append('file', new Blob([collected.text], { type: 'text/plain' }), 'guidebook.txt');
    this.setError(null);
    this.setSubmitting(true);
    try {
      const result = await postForm('/ingest/upload', form, {
        magicLink: magicLink.value ?? undefined,
        timeoutMs: UPLOAD_TIMEOUT_MS,
      });
      const base = lead.value;
      lead.value = {
        email: base?.email ?? '',
        flow: base?.flow ?? '',
        guidebook_id: result.guidebook_id,
        guidebook_name: result.name,
        guidebook_created_at: result.created_at,
      };
      navigate('/workspace');
    } catch (error) {
      this.setSubmitting(false);
      if (error instanceof ApplicationError && hasCode(error, 'ERR_INVALID_MAGIC_LINK')) {
        clearSession();
        showBanner(messageFor(error.code));
        navigate('/');
        return;
      }
      this.setError(this.generateErrorMessage(error));
    }
  };

  private generateErrorMessage(error: unknown): string {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      return 'This is taking longer than expected — it may still complete. Check back in a moment.';
    }
    if (!(error instanceof ApplicationError)) {
      return 'Something went wrong. Please try again.';
    }
    if (hasCode(error, 'ERR_RATE_LIMIT')) {
      return `${messageFor(error.code)} (retry in ${error.details.retry_after_s}s)`;
    }
    return messageFor(error.code);
  }
}

customElements.define('template-screen', TemplateScreen);
