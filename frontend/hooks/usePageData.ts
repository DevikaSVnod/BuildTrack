"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  readPageCache,
  readCacheAge,
  writePageCache,
  clearPageCache,
  PAGE_STALE_MS,
} from "@/lib/pageCache";

export function usePageData<T>(
  key: string,
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  const dataRef = useRef<T | null>(null);
  fetcherRef.current = fetcher;
  dataRef.current = data;

  // Restore cache before first paint (client only, after hydration).
  useLayoutEffect(() => {
    const cached = readPageCache<T>(key);
    if (cached) {
      setData(cached);
      setLoading(false);
    }
  }, [key]);

  const load = useCallback(
    async (bust = false) => {
      if (bust) clearPageCache(key);

      const cached = bust ? null : readPageCache<T>(key);
      const age = bust ? null : readCacheAge(key);

      if (cached) {
        setData(cached);
        setLoading(false);
        // Fresh cache — show instantly, skip network on back-navigation.
        if (age !== null && age < PAGE_STALE_MS) {
          setRefreshing(false);
          return;
        }
        setRefreshing(true);
      } else if (!dataRef.current) {
        setLoading(true);
      }
      setError(null);

      try {
        const fresh = await fetcherRef.current();
        writePageCache(key, fresh);
        setData(fresh);
      } catch {
        if (!cached) setError("Could not load data. Please try again.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, ...deps],
  );

  useEffect(() => {
    load();
  }, [load]);

  const reload = useCallback(() => load(true), [load]);

  return { data, loading, refreshing, error, reload, setData };
}
