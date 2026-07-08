import { signal } from '@preact/signals-core';

/** One sent guest message with its generated reply (`responsePairs`, §11.2). */
export interface ResponsePair {
  readonly message: string;
  readonly response: string;
}

/**
 * BYOK Claude key of the generate screen — JS memory only (F-29 / US-06 / §11.4): survives
 * in-app navigation through the menu, never mirrored to any storage; a hard reload or tab close
 * wipes it naturally.
 */
export const byokKey = signal<string>('');

/** Guest-message draft of the generate screen — same lifecycle as {@link byokKey} (US-06 / §11.2). */
export const guestMessage = signal<string>('');

/** Message → reply history of the generate screen (F-29 / US-06 / §11.2). */
export const responsePairs = signal<readonly ResponsePair[]>([]);
