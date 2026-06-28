import { describe, expect, it } from 'vitest';

import { ApplicationError, isRetryable, messageFor, parseErrorEnvelope } from './errors';

describe('parseErrorEnvelope', () => {
  it('returns an ApplicationError for an error envelope', () => {
    const err = parseErrorEnvelope({
      error: {
        code: 'ERR_RATE_LIMIT',
        message: 'slow',
        details: { scope: 'ip', retry_after_s: 5 },
      },
    });
    expect(err).toBeInstanceOf(ApplicationError);
    expect(err?.code).toBe('ERR_RATE_LIMIT');
    expect(err?.details).toEqual({ scope: 'ip', retry_after_s: 5 });
  });

  it('returns null for a success payload or non-object', () => {
    expect(parseErrorEnvelope({ response_text: 'hi' })).toBeNull();
    expect(parseErrorEnvelope(null)).toBeNull();
  });
});

describe('isRetryable', () => {
  it('is true only for retryable upstream errors', () => {
    expect(isRetryable(new ApplicationError('ERR_UPSTREAM_LLM', 'x', { retryable: true }))).toBe(
      true,
    );
    expect(isRetryable(new ApplicationError('ERR_UPSTREAM_EMAIL', 'x', { retryable: true }))).toBe(
      true,
    );
  });

  it('is false for non-retryable or other codes', () => {
    expect(isRetryable(new ApplicationError('ERR_UPSTREAM_LLM', 'x', { retryable: false }))).toBe(
      false,
    );
    expect(isRetryable(new ApplicationError('ERR_RATE_LIMIT', 'x', {}))).toBe(false);
  });
});

describe('messageFor', () => {
  it('returns a message for a code', () => {
    expect(messageFor('ERR_INVALID_MAGIC_LINK')).toMatch(/invalid|expired/i);
  });
});
