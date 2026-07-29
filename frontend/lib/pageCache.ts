const PREFIX = "bt:page:";
/** Keep cached page data for 5 minutes. */
const TTL_MS = 5 * 60 * 1000;
/** Skip background refetch if cache is newer than this (instant back-navigation). */
export const PAGE_STALE_MS = 3 * 60 * 1000;

type CacheEntry<T> = { ts: number; data: T };

const memory = new Map<string, CacheEntry<unknown>>();

/** Empty list caches often come from a failed load — always refetch them. */
export function isStaleEmptyList(data: unknown): boolean {
  return Array.isArray(data) && data.length === 0;
}

/** Dashboard cache must include projects[]; prefetch once wrote a different shape. */
export function isValidDashboardCache(data: unknown): boolean {
  return (
    !!data &&
    typeof data === "object" &&
    Array.isArray((data as { projects?: unknown }).projects)
  );
}

function readSessionEntry<T>(key: string): CacheEntry<T> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(`${PREFIX}${key}`);
    if (!raw) return null;
    const entry = JSON.parse(raw) as CacheEntry<T>;
    if (Date.now() - entry.ts > TTL_MS) {
      sessionStorage.removeItem(`${PREFIX}${key}`);
      return null;
    }
    return entry;
  } catch {
    return null;
  }
}

function getEntry<T>(key: string): CacheEntry<T> | null {
  const mem = memory.get(key) as CacheEntry<T> | undefined;
  if (mem && Date.now() - mem.ts <= TTL_MS) return mem;
  if (mem) memory.delete(key);

  const session = readSessionEntry<T>(key);
  if (session) {
    memory.set(key, session as CacheEntry<unknown>);
    return session;
  }
  return null;
}

export function readPageCache<T>(key: string): T | null {
  const entry = getEntry<T>(key);
  if (!entry) return null;
  if (isStaleEmptyList(entry.data)) {
    clearPageCache(key);
    return null;
  }
  return entry.data;
}

export function readCacheAge(key: string): number | null {
  const entry = getEntry<unknown>(key);
  if (!entry) return null;
  return Date.now() - entry.ts;
}

export function writePageCache<T>(key: string, data: T): void {
  const entry: CacheEntry<T> = { ts: Date.now(), data };
  memory.set(key, entry as CacheEntry<unknown>);
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(`${PREFIX}${key}`, JSON.stringify(entry));
  } catch {
    // sessionStorage full or unavailable
  }
}

export function clearPageCache(key: string): void {
  memory.delete(key);
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(`${PREFIX}${key}`);
}
