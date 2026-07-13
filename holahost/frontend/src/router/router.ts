import { currentPath } from '../state/route';
import { magicLink } from '../state/session';
import { normalizePath } from '../utils/url';
import { FALLBACK_TAG, ROUTES } from './routes';

const ROOT_SELECTOR = '#root';

export interface Resolved {
  /** Effective path after the guard (may differ from the requested path on redirect). */
  readonly path: string;
  /** Custom Element tag to mount. */
  readonly tag: string;
}

/**
 * Resolve a path to the screen tag to mount, applying the magic-link guard (§11.1).
 *
 * Matching is trailing-slash tolerant (`/guidebook/` ≡ `/guidebook`, §11.1); the returned path is
 * the canonical one. Unknown paths (including the retired `/workspace*`) and guarded-away
 * protected paths (no `magicLink`) resolve to the entrypoint at `/` — silently, since the magic
 * link may simply have expired (§11.1).
 */
export function resolveScreen(path: string): Resolved {
  const normalized = normalizePath(path);
  const route = ROUTES[normalized];
  if (!route || (route.protected && magicLink.value === null)) {
    return { path: '/', tag: FALLBACK_TAG };
  }
  return { path: normalized, tag: route.tag };
}

function mount(tag: string): void {
  const root = document.querySelector(ROOT_SELECTOR);
  if (!root) {
    throw new Error(`router: "${ROOT_SELECTOR}" not found`);
  }
  root.replaceChildren(document.createElement(tag));
}

function renderCurrentLocation(): void {
  const { path, tag } = resolveScreen(window.location.pathname);
  if (path !== window.location.pathname) {
    history.replaceState(null, '', path);
  }
  currentPath.value = path;
  mount(tag);
}

/** Navigate to a path (History API push) and mount the resolved screen (§11.1). */
export function navigate(requestedPath: string): void {
  const { path, tag } = resolveScreen(requestedPath);
  history.pushState(null, '', path);
  currentPath.value = path;
  mount(tag);
}

function onLinkClick(event: MouseEvent): void {
  if (!(event.target instanceof Element)) {
    return;
  }
  const link = event.target.closest('a[data-router-link]');
  if (link instanceof HTMLAnchorElement) {
    event.preventDefault();
    navigate(new URL(link.href).pathname);
  }
}

/** Start the router: handle popstate + `data-router-link` clicks, then mount the current location. */
export function start(): void {
  window.addEventListener('popstate', renderCurrentLocation);
  document.addEventListener('click', onLinkClick);
  renderCurrentLocation();
}
