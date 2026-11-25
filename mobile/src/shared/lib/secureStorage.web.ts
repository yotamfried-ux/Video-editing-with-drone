const fallbackMemory = new Map<string, string>();

function browserStorage(): Storage | null {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // Private browsing or SSR environment
  }
  return null;
}

export const secureStorage = {
  async getItem(key: string): Promise<string | null> {
    const store = browserStorage();
    if (store) {
      try {
        return store.getItem(key);
      } catch {
        // fall through
      }
    }
    return fallbackMemory.get(key) ?? null;
  },

  async setItem(key: string, value: string): Promise<void> {
    const store = browserStorage();
    if (store) {
      try {
        store.setItem(key, value);
        return;
      } catch {
        // fall through
      }
    }
    fallbackMemory.set(key, value);
  },

  async removeItem(key: string): Promise<void> {
    const store = browserStorage();
    if (store) {
      try {
        store.removeItem(key);
      } catch {
        // ignore
      }
    }
    fallbackMemory.delete(key);
  },
};
