import { lead } from '../state/session';

export interface Route {
  /** Custom Element tag to mount, or a resolver for state-dependent routes (§11.1). */
  readonly tag: string | (() => string);
  /** Requires a resolved magic link (§11.1 guard). */
  readonly protected: boolean;
}

const ENTRYPOINT_TAG = 'entrypoint-screen';

/** Path → screen mapping matching the state machine §1.3.1 / §11.1. */
export const ROUTES: Record<string, Route> = {
  '/': { tag: ENTRYPOINT_TAG, protected: false },
  '/sample-response': { tag: 'sample-response-screen', protected: false },
  '/capture-email': { tag: 'capture-email-screen', protected: false },
  // With a guidebook → answer guest messages; without → upload/generate one first (§1.3.4).
  '/workspace': {
    tag: () => (lead.value?.guidebook_id ? 'llm-key-msg-screen' : 'guidebook-screen'),
    protected: true,
  },
  '/workspace/upload': { tag: 'guidebook-screen', protected: true },
  '/workspace/template': { tag: 'template-screen', protected: true },
};

/** Screen to fall back to on an unknown or guarded-away path (§11.1). */
export const FALLBACK_TAG = ENTRYPOINT_TAG;

/** Whether a path requires a live magic-link session (§11.1 route guards). */
export function isProtectedPath(path: string): boolean {
  return ROUTES[path]?.protected === true;
}
