import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ postJson: vi.fn() }));
vi.mock('../router/router', () => ({ navigate: vi.fn() }));

import { postJson } from '../api/client';
import { ApplicationError } from '../api/errors';
import { navigate } from '../router/router';
import { captureFlow } from '../state/capture-flow';
import { sampleBudgetExhausted } from '../state/sample-budget';
import { sampleMessages } from '../state/sample-messages';
import { SampleResponseScreen } from './sample-response-screen';

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

const LIST = ['msg one', 'msg two', 'msg three'];

function stubMessagesFetch(payload: unknown = LIST): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(payload) });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('sample-response-screen', () => {
  let el: SampleResponseScreen;

  async function mount(): Promise<SampleResponseScreen> {
    el = new SampleResponseScreen();
    document.body.append(el);
    await tick();
    return el;
  }

  const field = (): HTMLTextAreaElement | null =>
    el.querySelector<HTMLTextAreaElement>('[data-message]');
  const send = (): void => el.querySelector<HTMLButtonElement>('[data-send]')?.click();

  beforeEach(() => {
    vi.mocked(postJson).mockReset();
    vi.mocked(navigate).mockReset();
    sampleBudgetExhausted.value = false;
    sampleMessages.value = null;
  });

  afterEach(() => {
    el.remove();
    sampleBudgetExhausted.value = false;
    sampleMessages.value = null;
    vi.unstubAllGlobals();
  });

  it('fetches the message list and prefills the first item into an editable field', async () => {
    const fetchMock = stubMessagesFetch();
    await mount();
    expect(fetchMock).toHaveBeenCalledWith('/config/sample_messages.json');
    expect(field()?.readOnly).toBe(false);
    expect(field()?.value).toBe('msg one');
  });

  it('reuses the cached list on remount without refetching', async () => {
    const fetchMock = stubMessagesFetch();
    await mount();
    el.remove();
    await mount();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(field()?.value).toBe('msg one');
  });

  it('sends the actual field content', async () => {
    stubMessagesFetch();
    await mount();
    vi.mocked(postJson).mockResolvedValue({ response_text: 'reply' });
    const area = field();
    if (area) {
      area.value = 'my own question';
    }
    send();
    await tick();
    expect(postJson).toHaveBeenCalledWith('/sample/generate', { message: 'my own question' });
  });

  it('appends each sent message with its reply as a pair, keeping previous pairs', async () => {
    stubMessagesFetch();
    await mount();
    vi.mocked(postJson).mockResolvedValueOnce({ response_text: 'reply one' });
    send();
    await tick();
    vi.mocked(postJson).mockResolvedValueOnce({ response_text: 'reply two' });
    send();
    await tick();
    const messages = el.querySelectorAll('[data-pair-message]');
    const replies = el.querySelectorAll('[data-pair-reply]');
    expect(messages).toHaveLength(2);
    expect(replies).toHaveLength(2);
    expect(messages[0]?.textContent).toBe('msg one');
    expect(replies[0]?.textContent).toBe('reply one');
    expect(messages[1]?.textContent).toBe('msg two');
    expect(replies[1]?.textContent).toBe('reply two');
  });

  it('prefills the next list item after a reply when the field still holds the sent prefill', async () => {
    stubMessagesFetch();
    await mount();
    vi.mocked(postJson).mockResolvedValue({ response_text: 'r' });
    send();
    await tick();
    expect(field()?.value).toBe('msg two');
  });

  it('does not overwrite manual input with the next prefill', async () => {
    stubMessagesFetch();
    await mount();
    const area = field();
    if (area) {
      area.value = 'custom question';
    }
    vi.mocked(postJson).mockResolvedValue({ response_text: 'r' });
    send();
    await tick();
    expect(field()?.value).toBe('custom question');
  });

  it('stops prefilling after the list is exhausted and keeps Send enabled', async () => {
    stubMessagesFetch(['only one']);
    await mount();
    vi.mocked(postJson).mockResolvedValue({ response_text: 'r' });
    send();
    await tick();
    expect(field()?.value).toBe('only one');
    expect(el.querySelector<HTMLButtonElement>('[data-send]')?.disabled).toBe(false);
  });

  it('leaves the field empty but editable when the list fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));
    await mount();
    expect(field()?.value).toBe('');
    expect(field()?.readOnly).toBe(false);
    vi.mocked(postJson).mockResolvedValue({ response_text: 'r' });
    const area = field();
    if (area) {
      area.value = 'typed anyway';
    }
    send();
    await tick();
    expect(postJson).toHaveBeenCalledWith('/sample/generate', { message: 'typed anyway' });
  });

  it('ignores a non-array message payload', async () => {
    stubMessagesFetch({ not: 'a list' });
    await mount();
    expect(sampleMessages.value).toBeNull();
    expect(field()?.value).toBe('');
  });

  it('blocks send on an empty message', async () => {
    stubMessagesFetch();
    await mount();
    const area = field();
    if (area) {
      area.value = '   ';
    }
    send();
    await tick();
    expect(postJson).not.toHaveBeenCalled();
    expect(el.querySelector('[data-error]')?.classList.contains('hidden')).toBe(false);
  });

  it('links the sample guidebook download to the published markdown object', async () => {
    stubMessagesFetch();
    await mount();
    const link = el.querySelector<HTMLAnchorElement>('[data-sample-download]');
    expect(link?.getAttribute('href')).toBe('/config/sample_guidebook.md');
    expect(link?.getAttribute('download')).toBe('sample_guidebook.md');
  });

  it('disables Send when the sample budget is exhausted', async () => {
    stubMessagesFetch();
    await mount();
    sampleBudgetExhausted.value = true;
    expect(el.querySelector<HTMLButtonElement>('[data-send]')?.disabled).toBe(true);
  });

  it('sets the budget signal on ERR_SAMPLE_BUDGET_EXHAUSTED', async () => {
    stubMessagesFetch();
    await mount();
    vi.mocked(postJson).mockRejectedValue(
      new ApplicationError('ERR_SAMPLE_BUDGET_EXHAUSTED', 'x', {
        reset_at: '2026-06-29T00:00:00Z',
      }),
    );
    send();
    await tick();
    expect(sampleBudgetExhausted.value).toBe(true);
  });

  it('Leave email sets flow=sample and navigates to capture', async () => {
    stubMessagesFetch();
    await mount();
    el.querySelector<HTMLButtonElement>('[data-leave-email]')?.click();
    expect(captureFlow.value).toBe('sample');
    expect(navigate).toHaveBeenCalledWith('/capture-email');
  });
});
