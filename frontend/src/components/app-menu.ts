import { effect } from '@preact/signals-core';

import { currentPath } from '../state/route';
import { magicLink } from '../state/session';

const ITEMS = [
  { path: '/guidebook', label: 'Guidebook' },
  { path: '/generate', label: 'Generate' },
] as const;

/**
 * Short workspace menu (F-28 / US-08 / §1.3.2): rendered on every screen while a magic-link
 * session is live, hidden entirely without one. Items are `a[data-router-link]` anchors — the
 * router's global click delegation handles the navigation (§11.1); the item matching the current
 * path carries `aria-current="page"`. Lives outside the router's `#root` (mounted by `main.ts`),
 * so it survives screen changes. Light DOM; self-registers as `<app-menu>`.
 */
export class AppMenu extends HTMLElement {
  private dispose: (() => void) | undefined;

  connectedCallback(): void {
    this.dispose = effect(() => {
      this.render(magicLink.value, currentPath.value);
    });
  }

  disconnectedCallback(): void {
    this.dispose?.();
    this.dispose = undefined;
  }

  private render(session: string | null, path: string): void {
    if (session === null) {
      this.hidden = true;
      this.replaceChildren();
      return;
    }
    this.hidden = false;
    // ITEMS are compile-time constants — safe to interpolate into the markup.
    const links = ITEMS.map((item) => {
      const active = item.path === path;
      const color = active ? 'text-blue-600' : 'text-gray-600 hover:text-gray-900';
      return `<a data-router-link href="${item.path}"${active ? ' aria-current="page"' : ''}
                 class="text-sm font-medium ${color}">${item.label}</a>`;
    }).join('');
    this.innerHTML = `
      <nav class="border-b border-gray-200 bg-white">
        <div class="mx-auto flex max-w-xl gap-6 px-4 py-3">${links}</div>
      </nav>`;
  }
}

customElements.define('app-menu', AppMenu);
