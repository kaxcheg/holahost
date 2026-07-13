import { effect, signal } from '@preact/signals-core';

import type { components } from '../api/generated';

/** Lead + guidebook metadata returned by `/api/magic-link/resolve` (§5.5). */
export type ResolveMagicLinkResult = components['schemas']['ResolveMagicLinkResult'];

const MAGIC_LINK_STORAGE_KEY = 'magic_link';

/** Resolved magic-link token; `null` after tab-close or a 401 resolve (§11.2). */
export const magicLink = signal<string | null>(null);

/** Lead data after a successful resolve (§11.2). */
export const lead = signal<ResolveMagicLinkResult | null>(null);

// Cached `/config/template_schema.json` (§10.6); element type is defined with the template screen (G3, F-16).
export const templateSchema = signal<readonly unknown[] | null>(null);

/**
 * Restore the session from sessionStorage and start mirroring `magicLink` back to it (§11.2).
 *
 * Reads the stored token BEFORE installing the mirror effect, so importing this module has no
 * side effects and the initial read cannot wipe the stored value. Call once at startup (F-19).
 */
export function initSession(): void {
  const stored = sessionStorage.getItem(MAGIC_LINK_STORAGE_KEY);
  if (stored) {
    magicLink.value = stored;
  }
  effect(() => {
    const token = magicLink.value;
    if (token === null) {
      sessionStorage.removeItem(MAGIC_LINK_STORAGE_KEY);
    } else {
      sessionStorage.setItem(MAGIC_LINK_STORAGE_KEY, token);
    }
  });
}

/**
 * Clear the resolved session (§11.4): drop the magic link and lead. Used on a 401
 * `ERR_INVALID_MAGIC_LINK` from any workspace call; the mirror effect also wipes sessionStorage.
 */
export function clearSession(): void {
  magicLink.value = null;
  lead.value = null;
}
