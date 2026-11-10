import { useEffect, useState } from "react";

/** The value as it was when it last stayed unchanged for `delay` milliseconds; the first value at once. */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    if (Object.is(settled, value)) {
      return;
    }
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [delay, settled, value]);
  return settled;
}
