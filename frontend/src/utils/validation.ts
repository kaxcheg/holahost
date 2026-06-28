import {
  EMAIL_MAX_LENGTH,
  EMAIL_REGEX,
  MAX_GUEST_MESSAGE_LENGTH,
} from '../api/constants.generated';

// Re-exported for UI affordances (char counters, maxlength) — single source is the generated module.
export { EMAIL_MAX_LENGTH, MAX_GUEST_MESSAGE_LENGTH };

/**
 * Client-side email check (UX only; the backend is authoritative, §10.7).
 *
 * @param email - Raw email input.
 * @returns `true` iff within {@link EMAIL_MAX_LENGTH} and matching the shared {@link EMAIL_REGEX}.
 */
export function isValidEmail(email: string): boolean {
  return email.length <= EMAIL_MAX_LENGTH && EMAIL_REGEX.test(email);
}

/**
 * Client-side guest-message check (UX only; the backend re-validates, §9.0).
 *
 * @param text - Raw message input.
 * @returns `true` iff non-empty after trimming and within {@link MAX_GUEST_MESSAGE_LENGTH}.
 */
export function isValidGuestMessage(text: string): boolean {
  const trimmed = text.trim();
  return trimmed.length > 0 && trimmed.length <= MAX_GUEST_MESSAGE_LENGTH;
}
