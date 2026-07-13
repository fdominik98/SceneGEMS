import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

const KEY_PREFIX = "scenegems:";

function readPersisted<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + key);
    if (raw === null) {
      return fallback;
    }
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/**
 * Drop-in replacement for `useState` that mirrors the value into `localStorage`,
 * so user edits survive a hard refresh. The value must be JSON-serializable.
 */
export function usePersistedState<T>(
  key: string,
  initialValue: T | (() => T)
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    const fallback =
      typeof initialValue === "function" ? (initialValue as () => T)() : initialValue;
    return readPersisted(key, fallback);
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(KEY_PREFIX + key, JSON.stringify(value));
    } catch {
      // Ignore quota / serialization errors; persistence is best-effort.
    }
  }, [key, value]);

  return [value, setValue];
}
