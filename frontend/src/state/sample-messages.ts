import { signal } from '@preact/signals-core';

/**
 * Ordered sample guest messages fetched once from `/config/sample_messages.json` (§11.2, US-01).
 *
 * `null` until the sample screen loads the list; stays `null` when the fetch fails or the payload
 * is not an array of non-empty strings — the message field then starts empty but stays editable.
 */
export const sampleMessages = signal<readonly string[] | null>(null);
