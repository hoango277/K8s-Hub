"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Read and write a localStorage value, safely with server-side rendering.
 *
 * WHY THIS HOOK EXISTS:
 *
 * Pages are pre-rendered on the server, where there is no localStorage.
 * Reading it directly during render makes server and browser output diverge,
 * and React reports a hydration error.
 *
 * The previous approach used `useSyncExternalStore` with an empty `subscribe`
 * function. It was WRONG in a subtle way: React takes the value at hydration
 * and never reads it again, and an empty `subscribe` never reports a change —
 * so the stored value was never applied. Places that happened to re-render for
 * some other reason (a data query, say) accidentally worked; places that
 * didn't were broken. The sidebar was one that didn't, and it always reopened
 * in its default state.
 *
 * Here we deliberately render twice: the first pass returns `null` (matching
 * the server), and only after mounting do we read the real value. Exactly one
 * extra render, which is the unavoidable price of not breaking hydration.
 */
export function useLocalStorage(key: string): [string | null, (value: string) => void] {
  const [value, setValue] = useState<string | null>(null);

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(key);
    } catch {
      // The browser blocks storage (private window, cookies blocked) — treat
      // it as having no value, don't break the whole page.
    }
    if (stored === null) return;

    // This is exactly the case the rule below allows: reading state from an
    // external system (localStorage) that only exists in the browser. Runs
    // once per key, no re-render loop.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setValue(stored);
  }, [key]);

  const save = useCallback(
    (next: string) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // If we can't persist, we only lose memory across visits; the current
        // session keeps working normally.
      }
    },
    [key],
  );

  return [value, save];
}
