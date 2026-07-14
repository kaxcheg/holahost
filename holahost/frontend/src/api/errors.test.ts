import { describe, expect, it } from 'vitest';

import { ApplicationError, hasCode, isRetryable, messageFor, parseErrorEnvelope } from './errors';

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
    expect(
      isRetryable(
        new ApplicationError('ERR_UPSTREAM_LLM', 'x', { upstream_status: 502, retryable: true }),
      ),
    ).toBe(true);
    expect(isRetryable(new ApplicationError('ERR_UPSTREAM_EMAIL', 'x', { retryable: true }))).toBe(
      true,
    );
  });

  it('is false for non-retryable or other codes', () => {
    expect(
      isRetryable(
        new ApplicationError('ERR_UPSTREAM_LLM', 'x', { upstream_status: 400, retryable: false }),
      ),
    ).toBe(false);
    expect(
      isRetryable(new ApplicationError('ERR_RATE_LIMIT', 'x', { scope: 'ip', retry_after_s: 5 })),
    ).toBe(false);
  });
});

describe('hasCode', () => {
  it('narrows code-specific details type-safely (no cast)', () => {
    const err: ApplicationError = new ApplicationError('ERR_RATE_LIMIT', 'slow', {
      scope: 'ip',
      retry_after_s: 7,
    });
    expect(hasCode(err, 'ERR_RATE_LIMIT')).toBe(true);
    expect(hasCode(err, 'ERR_NOT_FOUND')).toBe(false);
    if (hasCode(err, 'ERR_RATE_LIMIT')) {
      expect(err.details.retry_after_s).toBe(7);
    }
  });
});

describe('messageFor', () => {
  it('returns a message for a code', () => {
    expect(messageFor('ERR_INVALID_MAGIC_LINK')).toMatch(/invalid|expired/i);
  });
});
