import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { currentPath } from '../state/route';
import { magicLink } from '../state/session';
import { AppMenu } from './app-menu';

describe('app-menu', () => {
  let el: AppMenu;

  beforeEach(() => {
    magicLink.value = null;
    currentPath.value = '/';
    el = new AppMenu();
    document.body.append(el);
  });

  afterEach(() => {
    el.remove();
    magicLink.value = null;
    currentPath.value = '/';
  });

  it('is hidden without a session', () => {
    expect(el.hidden).toBe(true);
    expect(el.querySelector('nav')).toBeNull();
  });

  it('renders both router links when a session is live', () => {
    magicLink.value = 'tok';
    const links = el.querySelectorAll('a[data-router-link]');
    expect([...links].map((a) => a.getAttribute('href'))).toEqual(['/guidebook', '/generate']);
    expect(el.textContent).toContain('Guidebook');
    expect(el.textContent).toContain('Generate');
  });

  it('marks the current screen item as active', () => {
    magicLink.value = 'tok';
    currentPath.value = '/generate';
    expect(el.querySelector('a[href="/generate"]')?.getAttribute('aria-current')).toBe('page');
    expect(el.querySelector('a[href="/guidebook"]')?.hasAttribute('aria-current')).toBe(false);
    currentPath.value = '/guidebook';
    expect(el.querySelector('a[href="/guidebook"]')?.getAttribute('aria-current')).toBe('page');
  });

  it('marks no item active outside the menu screens', () => {
    magicLink.value = 'tok';
    currentPath.value = '/template';
    expect(el.querySelector('[aria-current]')).toBeNull();
  });

  it('hides again when the session is cleared', () => {
    magicLink.value = 'tok';
    expect(el.hidden).toBe(false);
    magicLink.value = null;
    expect(el.hidden).toBe(true);
    expect(el.querySelector('nav')).toBeNull();
  });
});
