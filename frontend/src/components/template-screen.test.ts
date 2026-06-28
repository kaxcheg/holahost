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
