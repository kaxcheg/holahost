import { API_BASE_URL } from '../config';
import { ApplicationError, isRetryable, parseErrorEnvelope } from './errors';
import type { paths } from './generated';

const MAGIC_LINK_HEADER = 'X-Magic-Link';
const API_KEY_HEADER = 'X-Api-Key';
// Client timeout, shorter than the Function URL hard timeout of 90s (§10.2).
const TIMEOUT_MS = 30_000;
const RETRY_DELAYS_MS = [1000, 2000, 4000] as const;

export interface RequestOptions {
  /** Magic-link token; injected as the X-Magic-Link header when present (§10.3). */
  magicLink?: string;
  /** BYOK Claude key; injected as the X-Api-Key header when present (only `/generate`, §11.4). */
  byok?: string;
  /** Caller abort signal, combined with the internal timeout. */
  signal?: AbortSignal;
}

type PostOp<P extends keyof paths> = paths[P] extends { post: infer O } ? O : never;
type GetOp<P extends keyof paths> = paths[P] extends { get: infer O } ? O : never;
type JsonContent<T> = T extends { content: { 'application/json': infer V } } ? V : never;
type SuccessBody<O> = O extends { responses: { 200: infer R } } ? JsonContent<R> : never;
type JsonRequestBody<O> = O extends { requestBody: { content: { 'application/json': infer B } } }
  ? B
  : never;

type JsonPostPath = {
  [P in keyof paths]: PostOp<P> extends {
    requestBody: { content: { 'application/json': unknown } };
  }
    ? P
    : never;
}[keyof paths];
type FormPostPath = {
  [P in keyof paths]: PostOp<P> extends {
    requestBody: { content: { 'multipart/form-data': unknown } };
  }
    ? P
    : never;
}[keyof paths];
type GetPathName = {
  [P in keyof paths]: paths[P] extends { get: object } ? P : never;
}[keyof paths];

async function request<R>(path: string, init: RequestInit, opts: RequestOptions): Promise<R> {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    TIMEOUT_MS,
  );
  opts.signal?.addEventListener('abort', () => controller.abort(opts.signal?.reason), {
    once: true,
  });

  const headers = new Headers(init.headers);
  if (opts.magicLink) {
    headers.set(MAGIC_LINK_HEADER, opts.magicLink);
  }
  if (opts.byok) {
    headers.set(API_KEY_HEADER, opts.byok);
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    const payload: unknown = await response.json();
    const appError = parseErrorEnvelope(payload);
    if (appError) {
      throw appError;
    }
    return payload as R;
  } finally {
    clearTimeout(timer);
  }
}

/** POST a JSON body to a typed endpoint and return its parsed success payload (§11.3). */
export function postJson<P extends JsonPostPath>(
  path: P,
  body: JsonRequestBody<PostOp<P>>,
  opts: RequestOptions = {},
): Promise<SuccessBody<PostOp<P>>> {
  return request<SuccessBody<PostOp<P>>>(
    path,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    opts,
  );
}

/** GET a typed endpoint and return its parsed success payload. */
export function get<P extends GetPathName>(
  path: P,
  opts: RequestOptions = {},
): Promise<SuccessBody<GetOp<P>>> {
  return request<SuccessBody<GetOp<P>>>(path, { method: 'GET' }, opts);
}

/** POST a multipart form to a typed endpoint (file upload, §5.6). */
export function postForm<P extends FormPostPath>(
  path: P,
  form: FormData,
  opts: RequestOptions = {},
): Promise<SuccessBody<PostOp<P>>> {
  return request<SuccessBody<PostOp<P>>>(path, { method: 'POST', body: form }, opts);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/** Run `fn`, retrying retryable upstream failures with exponential backoff (1s/2s/4s, max 3, §10.8). */
export async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      const canRetry =
        error instanceof ApplicationError && isRetryable(error) && attempt < RETRY_DELAYS_MS.length;
      if (!canRetry) {
        throw error;
      }
      await delay(RETRY_DELAYS_MS[attempt] ?? 0);
    }
  }
}
