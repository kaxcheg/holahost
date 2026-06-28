import type { components } from './generated';

export type ErrorEnvelope = components['schemas']['ErrorEnvelope'];
export type ErrorCode = ErrorEnvelope['error']['code'];
type ErrorDetails = ErrorEnvelope['error']['details'];

/** A typed backend error from the `{ error: { code, message, details } }` envelope (§5.0 / §10.8). */
export class ApplicationError extends Error {
  readonly code: ErrorCode;
  readonly details: ErrorDetails;

  constructor(code: ErrorCode, message: string, details: ErrorDetails) {
    super(message);
    this.name = 'ApplicationError';
    this.code = code;
    this.details = details;
  }
}

/**
 * Parse a response body as an error envelope (§5.0).
 *
 * @returns An {@link ApplicationError} if `body` is an error envelope, otherwise `null` (success payload).
 */
export function parseErrorEnvelope(body: unknown): ApplicationError | null {
  if (
    typeof body === 'object' &&
    body !== null &&
    'error' in body &&
    typeof (body as { error: unknown }).error === 'object' &&
    (body as { error: unknown }).error !== null
  ) {
    const { error } = body as ErrorEnvelope;
    return new ApplicationError(error.code, error.message, error.details);
  }
  return null;
}

/** Whether the client should auto-retry with backoff: retryable upstream failures only (§10.8). */
export function isRetryable(error: ApplicationError): boolean {
  if (error.code !== 'ERR_UPSTREAM_LLM' && error.code !== 'ERR_UPSTREAM_EMAIL') {
    return false;
  }
  return (error.details as { retryable?: boolean }).retryable === true;
}

// UI copy per error code (MVP — English only, §2.7). Exhaustive over ErrorCode (compile-time checked).
const UI_MESSAGES: Record<ErrorCode, string> = {
  ERR_INVALID_API_KEY: 'Invalid API key. Check your Claude key and try again.',
  ERR_INVALID_MAGIC_LINK: 'Your link is invalid or has expired. Please request a new one.',
  ERR_NOT_FOUND: 'The requested resource was not found.',
  ERR_NO_GUIDEBOOK: 'No guidebook yet — upload or generate one first.',
  ERR_EMAIL_CONFLICT: 'Something went wrong. Please try again.',
  ERR_PAYLOAD_TOO_LARGE: 'That file is too large.',
  ERR_TOO_MANY_CHUNKS: 'That document is too large to process.',
  ERR_UNSUPPORTED_MEDIA_TYPE: 'Unsupported file type.',
  ERR_EMPTY_DOCUMENT: 'No text could be extracted from that file.',
  ERR_INVALID_PAYLOAD: 'Please check the highlighted field and try again.',
  ERR_RATE_LIMIT: 'Too many requests. Please wait a moment and try again.',
  ERR_SAMPLE_BUDGET_EXHAUSTED:
    'The daily sample limit was reached. Try again tomorrow or use your own key.',
  ERR_UPSTREAM_LLM: 'The AI service is temporarily unavailable. Please try again.',
  ERR_UPSTREAM_EMAIL: 'We could not send the email. Please try again.',
  ERR_INTERNAL: 'Something went wrong. Please try again.',
};

/** Human-readable UI message for an error code (§5.8). */
export function messageFor(code: ErrorCode): string {
  return UI_MESSAGES[code];
}
