import { describe, expect, it } from 'vitest';

import {
  EMAIL_MAX_LENGTH,
  isValidEmail,
  isValidGuestMessage,
  MAX_GUEST_MESSAGE_LENGTH,
} from './validation';

describe('isValidEmail', () => {
  it('accepts a well-formed address', () => {
    expect(isValidEmail('host@example.com')).toBe(true);
  });

  it('rejects a malformed address', () => {
    expect(isValidEmail('not-an-email')).toBe(false);
    expect(isValidEmail('a@b')).toBe(false);
  });

  it('rejects an over-long address', () => {
    expect(isValidEmail(`${'a'.repeat(EMAIL_MAX_LENGTH)}@example.com`)).toBe(false);
  });
});

describe('isValidGuestMessage', () => {
  it('accepts non-empty text within the cap', () => {
    expect(isValidGuestMessage('hello')).toBe(true);
  });

  it('rejects empty or whitespace-only text', () => {
    expect(isValidGuestMessage('   ')).toBe(false);
  });

  it('rejects text over the cap', () => {
    expect(isValidGuestMessage('x'.repeat(MAX_GUEST_MESSAGE_LENGTH + 1))).toBe(false);
  });
});
