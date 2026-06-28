import { afterEach, describe, expect, it, vi } from 'vitest';

import { get, postJson, withRetry } from './client';
import { ApplicationError } from './errors';

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ json: () => Promise.resolve(payload) });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('postJson', () => {
  it('sends URL, headers and body and returns the payload', async () => {
    const fetchMock = stubFetch({ response_text: 'hi' });
    const result = await postJson('/sample/generate', { message: 'q' }, { magicLink: 'tok' });

    expect(result).toEqual({ response_text: 'hi' });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/sample/generate');
    expect(init.method).toBe('POST');
    const headers = init.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-Magic-Link')).toBe('tok');
    expect(init.body).toBe(JSON.stringify({ message: 'q' }));
  });

  it('throws ApplicationError on an error envelope', async () => {
    stubFetch({
      error: {
        code: 'ERR_RATE_LIMIT',
        message: 'slow',
        details: { scope: 'ip', retry_after_s: 5 },
      },
    });
    await expect(postJson('/sample/generate', { message: 'q' })).rejects.toBeInstanceOf(
      ApplicationError,
    );
  });
});

describe('get', () => {
  it('issues a GET with the magic-link header', async () => {
    const fetchMock = stubFetch({
      email: 'a@b.co',
      flow: 'guidebook',
      guidebook_id: null,
      guidebook_name: null,
      guidebook_created_at: null,
    });
    await get('/magic-link/resolve', { magicLink: 'tok' });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/magic-link/resolve');
    expect(init.method).toBe('GET');
    expect((init.headers as Headers).get('X-Magic-Link')).toBe('tok');
  });
});

describe('withRetry', () => {
  it('does not retry a non-retryable error', async () => {
    const fn = vi.fn().mockRejectedValue(new ApplicationError('ERR_INVALID_PAYLOAD', 'bad', {}));
    await expect(withRetry(fn)).rejects.toBeInstanceOf(ApplicationError);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('retries a retryable upstream error then succeeds', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const fn = vi.fn(() => {
      calls += 1;
      return calls < 2
        ? Promise.reject(new ApplicationError('ERR_UPSTREAM_LLM', 'down', { retryable: true }))
        : Promise.resolve('ok');
    });

    const promise = withRetry(fn);
    await vi.advanceTimersByTimeAsync(1000);

    await expect(promise).resolves.toBe('ok');
    expect(fn).toHaveBeenCalledTimes(2);
  });
});
