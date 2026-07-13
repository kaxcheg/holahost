import { signal } from '@preact/signals-core';

/**
 * Global error-banner message (§11.3 / §11.4): non-null shows the dismissible `<error-banner>`,
 * `null` hides it. Used for cross-cutting errors (e.g. an expired magic link redirect), not for
 * per-field form errors, which screens render inline.
 */
export const bannerMessage = signal<string | null>(null);

/** Show a global error banner with `message` (§11.3). */
export function showBanner(message: string): void {
  bannerMessage.value = message;
}

/** Hide the global error banner (§11.3). */
export function clearBanner(): void {
  bannerMessage.value = null;
}
