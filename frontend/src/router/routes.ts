import { normalizePath } from '../utils/url';

export interface Route {
  /** Custom Element tag to mount (§11.1 — one screen per path, no state-dependent resolvers). */
  readonly tag: string;
  /** Requires a resolved magic link (§11.1 guard). */
  readonly protected: boolean;
}

const ENTRYPOINT_TAG = 'entrypoint-screen';

/**
 * Path → screen mapping matching the state machine §1.3.1 / §11.1 (Spec-extend 2026-07-07:
 * per-screen paths; the state-resolved `/workspace*` family is retired — old URLs fall back to
 * the entrypoint via the unknown-path branch).
 */
export const ROUTES: Record<string, Route> = {
  '/': { tag: ENTRYPOINT_TAG, protected: false },
  '/sample-response': { tag: 'sample-response-screen', protected: false },
  '/capture-email': { tag: 'capture-email-screen', protected: false },
  '/guidebook': { tag: 'guidebook-screen', protected: true },
  '/template': { tag: 'template-screen', protected: true },
  '/generate': { tag: 'generate-screen', protected: true },
};

/** Screen to fall back to on an unknown or guarded-away path (§11.1). */
export const FALLBACK_TAG = ENTRYPOINT_TAG;

/** Whether a path requires a live magic-link session (§11.1 route guards); trailing-slash tolerant. */
export function isProtectedPath(path: string): boolean {
  return ROUTES[normalizePath(path)]?.protected === true;
}
