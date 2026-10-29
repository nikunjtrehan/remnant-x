import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
// Keep tests independent of Node 25's experimental filesystem-backed storage.
const items = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (key: string) => items.get(key) ?? null,
  setItem: (key: string, value: string) => items.set(key, value),
  removeItem: (key: string) => items.delete(key), clear: () => items.clear(),
});
afterEach(cleanup);
