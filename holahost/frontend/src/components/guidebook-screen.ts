import { postForm, UPLOAD_TIMEOUT_MS } from '../api/client';
import { ApplicationError, hasCode, messageFor } from '../api/errors';
import { navigate } from '../router/router';
import { showBanner } from '../state/error-banner';
import { clearSession, lead, magicLink } from '../state/session';

/** Render `max_bytes` as a rounded MB figure for the size-limit message (value comes from the backend). */
function formatMb(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

/**
 * Guidebook workspace (F-15 / §1.3.2 / §1.3.4 / §5.6).
 *
 * Shows the current guidebook (from the `lead` signal) or "no guidebook yet"; offers a file upload
 * (`name` + file → `POST /api/ingest/upload`), a path to the template form, and Next into the
 * answer screen. Upload is enabled only once both `name` and a file are chosen; Next only once a
 * guidebook exists. During upload it swaps to `<processing-screen>`. On success it updates `lead`
 * (so Next enables; Next navigates explicitly to `/generate`, §11.1). Light DOM; self-registers.
 */
export class GuidebookScreen extends HTMLElement {
  connectedCallback(): void {
    this.addEventListener('click', this.onClick);
    this.addEventListener('input', this.onFormChange);
    this.addEventListener('change', this.onFormChange);
    this.renderMain();
  }

  disconnectedCallback(): void {
    this.removeEventListener('click', this.onClick);
    this.removeEventListener('input', this.onFormChange);
    this.removeEventListener('change', this.onFormChange);
  }

  private renderMain(): void {
    const gb = lead.value;
    const hasGuidebook = Boolean(gb?.guidebook_id);
    const created = gb?.guidebook_created_at
      ? new Date(gb.guidebook_created_at).toLocaleDateString()
      : '';
    this.innerHTML = `
      <section class="mx-auto flex max-w-lg flex-col gap-6 px-4 py-10">
        <div data-gb-info class="rounded-md bg-gray-50 px-4 py-3 text-sm"></div>
        <div class="flex flex-col gap-4">
          <label class="flex flex-col gap-1 text-sm font-medium">
            Guidebook name
            <input data-name type="text" maxlength="200"
                   class="rounded-md border border-gray-300 px-3 py-2 font-normal focus:border-blue-500 focus:outline-none" />
          </label>
          <input data-file type="file" class="text-sm" />
          <button data-action="upload" type="button" disabled
                  class="self-start rounded-md bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-60">
            Upload
          </button>
          <p data-upload-hint class="text-xs text-gray-500"></p>
          <p data-error role="alert" class="hidden text-sm text-red-600"></p>
        </div>
        <div class="flex items-center gap-3 text-xs text-gray-400">
          <span class="h-px flex-1 bg-gray-200"></span>OR<span class="h-px flex-1 bg-gray-200"></span>
        </div>
        <button data-action="template" type="button"
                class="self-start rounded-md border border-gray-300 px-5 py-2.5 font-medium hover:bg-gray-50">
          Generate by template
        </button>
        <button data-action="next" type="button" ${hasGuidebook ? '' : 'disabled'}
                class="self-end rounded-md bg-green-600 px-5 py-2.5 font-medium text-white hover:bg-green-700 disabled:opacity-60">
          Next &rarr;
        </button>
      </section>`;
    const info = this.querySelector('[data-gb-info]');
    if (info) {
      info.textContent = hasGuidebook
        ? `Current guidebook: ${gb?.guidebook_name ?? 'untitled'}${created ? ` · ${created}` : ''}`
        : 'No guidebook yet — upload a file or generate one from a template.';
    }
    const nameInput = this.querySelector<HTMLInputElement>('[data-name]');
    if (nameInput) {
      // Prefill with the current name so replacing needs only a new file (US-04, 1:1_replace);
      // user data goes in via the value property, never interpolated into innerHTML.
      nameInput.value = gb?.guidebook_name ?? '';
    }
    this.updateUploadState();
  }

  private renderProcessing(): void {
    this.innerHTML = '<processing-screen message="Uploading your guidebook…"></processing-screen>';
  }

  private setError(message: string): void {
    const el = this.querySelector('[data-error]');
    if (el) {
      el.textContent = message;
      el.classList.remove('hidden');
    }
  }

  private updateUploadState(): void {
    const name = this.querySelector<HTMLInputElement>('[data-name]')?.value.trim() ?? '';
    const fileCount = this.querySelector<HTMLInputElement>('[data-file]')?.files?.length ?? 0;
    const ready = Boolean(name) && fileCount > 0;
    const button = this.querySelector<HTMLButtonElement>('[data-action="upload"]');
    if (button) {
      button.disabled = !ready;
    }
    // A disabled button gives no click feedback — the hint names what is still missing (US-04).
    const hint = this.querySelector('[data-upload-hint]');
    if (hint) {
      const missing = [...(name ? [] : ['a guidebook name']), ...(fileCount > 0 ? [] : ['a file'])];
      hint.textContent = missing.length ? `Add ${missing.join(' and ')} to enable Upload.` : '';
      hint.classList.toggle('hidden', ready);
    }
  }

  private readonly onFormChange = (): void => {
    this.updateUploadState();
  };

  private readonly onClick = (event: MouseEvent): void => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const action = event.target.closest('[data-action]')?.getAttribute('data-action');
    if (action === 'template') {
      navigate('/template');
    } else if (action === 'next') {
      navigate('/generate');
    } else if (action === 'upload') {
      void this.onUpload();
    }
  };

  private async onUpload(): Promise<void> {
    const name = this.querySelector<HTMLInputElement>('[data-name]')?.value.trim() ?? '';
    const file = this.querySelector<HTMLInputElement>('[data-file]')?.files?.[0];
    if (!name || !file) {
      return;
    }
    const form = new FormData();
    form.append('name', name);
    form.append('file', file);
    this.renderProcessing();
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
      this.renderMain();
    } catch (error) {
      if (error instanceof ApplicationError && hasCode(error, 'ERR_INVALID_MAGIC_LINK')) {
        clearSession();
        showBanner(messageFor(error.code));
        navigate('/');
        return;
      }
      this.renderMain();
      this.setError(this.uploadErrorMessage(error));
    }
  }

  /** Map an upload failure to a user-facing line (§5.8 / §10.8); detail values come from the backend. */
  private uploadErrorMessage(error: unknown): string {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      return 'Upload is taking longer than expected — it may still complete. Check back in a moment.';
    }
    if (!(error instanceof ApplicationError)) {
      return 'Something went wrong. Please try again.';
    }
    if (hasCode(error, 'ERR_PAYLOAD_TOO_LARGE')) {
      return `That file is too large (max ${formatMb(error.details.max_bytes)}).`;
    }
    if (hasCode(error, 'ERR_TOO_MANY_CHUNKS')) {
      return `That document is too large (max ${error.details.max_chunks} sections).`;
    }
    if (hasCode(error, 'ERR_UNSUPPORTED_MEDIA_TYPE')) {
      return `Unsupported file type. Allowed: ${error.details.allowed.join(', ')}.`;
    }
    if (hasCode(error, 'ERR_RATE_LIMIT')) {
      return `${messageFor(error.code)} (retry in ${error.details.retry_after_s}s)`;
    }
    return messageFor(error.code);
  }
}

customElements.define('guidebook-screen', GuidebookScreen);
