import { describe, expect, it } from 'vitest';

import { isEnvironment } from './config';

describe('isEnvironment', () => {
  it('accepts the deployment environments', () => {
    expect(isEnvironment('dev')).toBe(true);
    expect(isEnvironment('staging')).toBe(true);
    expect(isEnvironment('prod')).toBe(true);
  });

  it('rejects anything else', () => {
    expect(isEnvironment('production')).toBe(false);
    expect(isEnvironment('')).toBe(false);
    expect(isEnvironment(undefined)).toBe(false);
    expect(isEnvironment(null)).toBe(false);
  });
});
