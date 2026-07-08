import { signal } from '@preact/signals-core';

/**
 * Current SPA path as mounted by the router (F-28 / §11.1): written after guard resolution in
 * `navigate()` / `renderCurrentLocation()`; read by `<app-menu>` for the active item (US-08).
 */
export const currentPath = signal<string>('/');
