import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ postForm: vi.fn(), UPLOAD_TIMEOUT_MS: 90_000 }));
vi.mock('../router/router', () => ({ navigate: vi.fn() }));

import { postForm } from '../api/client';
import { navigate } from '../router/router';
import { lead, magicLink, templateSchema } from '../state/session';
import { TemplateScreen } from './template-screen';

const SCHEMA = [
  {
    name: 'property_name',
    label: 'Property name',
    required: true,
    max_length: 100,
    hint: 'e.g. Loft',
  },
  { name: 'wifi', label: 'Wifi', required: true, max_length: 100, hint: '' },
  { name: 'pets', label: 'Pets', required: false, max_length: 200, hint: '' },
];

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

function setField(el: HTMLElement, name: string, value: string): void {
  const field = el.querySelector<HTMLTextAreaElement>(`[data-field="${name}"]`);
  if (field) {
    field.value = value;
  }
}

function submit(el: HTMLElement): void {
  el.querySelector('[data-form]')?.dispatchEvent(new Event('submit', { cancelable: true }));
}

describe('template-screen', () => {
  let el: TemplateScreen;

  beforeEach(() => {
    vi.mocked(postForm).mockReset();
    vi.mocked(navigate).mockReset();
    magicLink.value = 'tok';
    lead.value = null;
    templateSchema.value = SCHEMA;
    el = new TemplateScreen();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
    templateSchema.value = null;
    lead.value = null;
    magicLink.value = null;
  });

  it('renders a field per schema entry from the cache', () => {
    expect(el.querySelectorAll('[data-field]')).toHaveLength(3);
    expect(el.querySelector('[data-field="property_name"]')).not.toBeNull();
  });

  it('blocks submit when a required field is empty', () => {
    submit(el);
    expect(postForm).not.toHaveBeenCalled();
    expect(el.querySelector('[data-error]')?.classList.contains('hidden')).toBe(false);
  });

  it('renders plain text and uploads with name=property_name on Generate', async () => {
    // vitest collapses postForm's single-path generic ReturnType to `never`; cast the value through it.
    vi.mocked(postForm).mockResolvedValue({
      guidebook_id: 'gb-2',
      name: 'Loft',
      created_at: '2026-06-28T00:00:00Z',
    } as never);
    setField(el, 'property_name', 'Loft');
    setField(el, 'wifi', 'pw123');
    submit(el);
    await tick();
    expect(postForm).toHaveBeenCalledWith(
      '/ingest/upload',
      expect.any(FormData),
      expect.objectContaining({ magicLink: 'tok', timeoutMs: 90_000 }),
    );
    const form = vi.mocked(postForm).mock.calls[0]?.[1] as FormData;
    expect(form.get('name')).toBe('Loft');
    expect(lead.value?.guidebook_id).toBe('gb-2');
    expect(navigate).toHaveBeenCalledWith('/workspace');
  });
});

describe('template-screen schema loading', () => {
  let el: TemplateScreen;

  function stubSchemaFetch(payload: unknown, ok = true, status = 200): void {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(payload) }),
    );
  }

  async function mount(): Promise<void> {
    el = new TemplateScreen();
    document.body.append(el);
    await tick();
  }

  beforeEach(() => {
    magicLink.value = 'tok';
    lead.value = null;
    templateSchema.value = null;
  });

  afterEach(() => {
    el.remove();
    templateSchema.value = null;
    lead.value = null;
    magicLink.value = null;
    vi.unstubAllGlobals();
  });

  it('renders the form from a fetched array schema and caches it', async () => {
    stubSchemaFetch(SCHEMA);
    await mount();
    expect(el.querySelectorAll('[data-field]')).toHaveLength(3);
    expect(templateSchema.value).toEqual(SCHEMA);
  });

  it('shows a visible load error and does not cache a non-array JSON payload', async () => {
    stubSchemaFetch({ error: { code: 'ERR_NOT_FOUND' } });
    await mount();
    const error = el.querySelector('[data-load-error]');
    expect(error).not.toBeNull();
    expect(error?.getAttribute('role')).toBe('alert');
    expect(templateSchema.value).toBeNull();
  });

  it('renders the load error again on remount after a non-array payload (no crash)', async () => {
    stubSchemaFetch({});
    await mount();
    el.remove();
    await mount();
    expect(el.querySelector('[data-load-error]')).not.toBeNull();
  });

  it('shows the load error when the body is not JSON (SPA fallback HTML)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.reject(new SyntaxError('Unexpected token <')),
      }),
    );
    await mount();
    expect(el.querySelector('[data-load-error]')).not.toBeNull();
  });

  it('shows the load error on a non-2xx response', async () => {
    stubSchemaFetch('irrelevant', false, 500);
    await mount();
    expect(el.querySelector('[data-load-error]')).not.toBeNull();
  });
});
