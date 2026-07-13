import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ postForm: vi.fn(), UPLOAD_TIMEOUT_MS: 90_000 }));
vi.mock('../router/router', () => ({ navigate: vi.fn() }));

import { postForm } from '../api/client';
import { navigate } from '../router/router';
import { lead, magicLink } from '../state/session';
import { GuidebookScreen } from './guidebook-screen';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

function setName(el: HTMLElement, value: string): void {
  const input = el.querySelector<HTMLInputElement>('[data-name]');
  if (input) {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
}

function setFile(el: HTMLElement): void {
  const input = el.querySelector<HTMLInputElement>('[data-file]');
  if (input) {
    Object.defineProperty(input, 'files', {
      value: [new File(['hello'], 'guide.pdf', { type: 'application/pdf' })],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

function click(el: HTMLElement, action: string): void {
  el.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)?.click();
}

describe('guidebook-screen', () => {
  let el: GuidebookScreen;

  beforeEach(() => {
    vi.mocked(postForm).mockReset();
    vi.mocked(navigate).mockReset();
    magicLink.value = 'tok';
    lead.value = null;
    el = new GuidebookScreen();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
    lead.value = null;
    magicLink.value = null;
  });

  it('shows "no guidebook yet" and disables Next when there is none', () => {
    expect(el.textContent).toContain('No guidebook yet');
    expect(el.querySelector<HTMLButtonElement>('[data-action="next"]')?.disabled).toBe(true);
  });

  it('shows the current guidebook and enables Next when one exists', () => {
    lead.value = {
      email: 'h@x.com',
      flow: 'guidebook',
      guidebook_id: 'gb-1',
      guidebook_name: 'Riverside Loft',
      guidebook_created_at: '2026-06-01T00:00:00Z',
    };
    el.remove();
    el = new GuidebookScreen();
    document.body.append(el);
    expect(el.textContent).toContain('Riverside Loft');
    expect(el.querySelector<HTMLButtonElement>('[data-action="next"]')?.disabled).toBe(false);
  });

  it('shows the enable-hint while Upload is disabled and hides it once ready', () => {
    const hint = el.querySelector('[data-upload-hint]');
    expect(hint?.textContent).toBe('Add a guidebook name and a file to enable Upload.');
    expect(hint?.classList.contains('hidden')).toBe(false);
    setName(el, 'My place');
    expect(hint?.textContent).toBe('Add a file to enable Upload.');
    setFile(el);
    expect(el.querySelector<HTMLButtonElement>('[data-action="upload"]')?.disabled).toBe(false);
    expect(hint?.classList.contains('hidden')).toBe(true);
  });

  it('prefills the name with the current guidebook so replacing needs only a file', () => {
    lead.value = {
      email: 'h@x.com',
      flow: 'guidebook',
      guidebook_id: 'gb-1',
      guidebook_name: 'Riverside Loft',
      guidebook_created_at: '2026-06-01T00:00:00Z',
    };
    el.remove();
    el = new GuidebookScreen();
    document.body.append(el);
    expect(el.querySelector<HTMLInputElement>('[data-name]')?.value).toBe('Riverside Loft');
    expect(el.querySelector('[data-upload-hint]')?.textContent).toBe(
      'Add a file to enable Upload.',
    );
    setFile(el);
    expect(el.querySelector<HTMLButtonElement>('[data-action="upload"]')?.disabled).toBe(false);
  });

  it('Generate by template navigates to the template screen', () => {
    click(el, 'template');
    expect(navigate).toHaveBeenCalledWith('/template');
  });

  it('Next navigates explicitly to the generate screen', () => {
    lead.value = {
      email: 'h@x.com',
      flow: 'guidebook',
      guidebook_id: 'gb-1',
      guidebook_name: 'Riverside Loft',
      guidebook_created_at: '2026-06-01T00:00:00Z',
    };
    el.remove();
    el = new GuidebookScreen();
    document.body.append(el);
    click(el, 'next');
    expect(navigate).toHaveBeenCalledWith('/generate');
  });

  it('uploads name + file and updates the lead on success', async () => {
    // vitest collapses postForm's single-path generic ReturnType to `never`; cast the value through it.
    vi.mocked(postForm).mockResolvedValue({
      guidebook_id: 'gb-9',
      name: 'My place',
      created_at: '2026-06-28T00:00:00Z',
    } as never);
    setName(el, 'My place');
    setFile(el);
    click(el, 'upload');
    await tick();
    expect(postForm).toHaveBeenCalledWith(
      '/ingest/upload',
      expect.any(FormData),
      expect.objectContaining({ magicLink: 'tok', timeoutMs: 90_000 }),
    );
    expect(lead.value?.guidebook_id).toBe('gb-9');
    expect(el.textContent).toContain('My place');
  });

  it('shows the backend size limit on ERR_PAYLOAD_TOO_LARGE', async () => {
    const { ApplicationError } = await import('../api/errors');
    vi.mocked(postForm).mockRejectedValue(
      new ApplicationError('ERR_PAYLOAD_TOO_LARGE', 'x', { max_bytes: 4_194_304 }),
    );
    setName(el, 'My place');
    setFile(el);
    click(el, 'upload');
    await tick();
    expect(el.querySelector('[data-error]')?.textContent).toContain('4 MB');
  });
});
