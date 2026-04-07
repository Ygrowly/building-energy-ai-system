import { createAbortError, recordPerf, startPerfSpan } from '@/utils/perf'

interface CacheEntry<T> {
  data: T
  updatedAt: number
}

export type RequestCachePersist = 'memory' | 'session'

export interface RequestCacheSnapshot<T> {
  data: T | null
  updatedAt: number | null
  ageMs: number
  isFresh: boolean
}

interface FetchRequestCacheOptions {
  force?: boolean
  persist?: RequestCachePersist
  signal?: AbortSignal
  ttlMs?: number
}

const SESSION_PREFIX = '__web_req_cache__:'
const memoryStore = new Map<string, CacheEntry<unknown>>()
const inFlight = new Map<string, Promise<unknown>>()

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function getSessionStorageKey(key: string): string {
  return `${SESSION_PREFIX}${key}`
}

function canUseSessionStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.sessionStorage !== 'undefined'
}

function readSessionEntry<T>(key: string): CacheEntry<T> | null {
  if (!canUseSessionStorage()) return null
  try {
    const raw = window.sessionStorage.getItem(getSessionStorageKey(key))
    if (!raw) return null
    const parsed = JSON.parse(raw) as CacheEntry<T>
    if (!parsed || typeof parsed.updatedAt !== 'number') return null
    return parsed
  } catch {
    return null
  }
}

function writeSessionEntry<T>(key: string, entry: CacheEntry<T>): void {
  if (!canUseSessionStorage()) return
  try {
    window.sessionStorage.setItem(getSessionStorageKey(key), JSON.stringify(entry))
  } catch {
    // Ignore storage write failures.
  }
}

function removeSessionEntry(key: string): void {
  if (!canUseSessionStorage()) return
  try {
    window.sessionStorage.removeItem(getSessionStorageKey(key))
  } catch {
    // Ignore storage remove failures.
  }
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw createAbortError()
  }
}

function bindAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise
  throwIfAborted(signal)

  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(createAbortError())
    signal.addEventListener('abort', onAbort, { once: true })

    promise.then(
      (value) => {
        signal.removeEventListener('abort', onAbort)
        resolve(value)
      },
      (error) => {
        signal.removeEventListener('abort', onAbort)
        reject(error)
      },
    )
  })
}

function resolveEntry<T>(key: string, persist: RequestCachePersist): CacheEntry<T> | null {
  const memoryEntry = memoryStore.get(key) as CacheEntry<T> | undefined
  if (memoryEntry) return memoryEntry
  if (persist === 'session') {
    const sessionEntry = readSessionEntry<T>(key)
    if (sessionEntry) {
      memoryStore.set(key, sessionEntry)
      return sessionEntry
    }
  }
  return null
}

function saveEntry<T>(key: string, data: T, persist: RequestCachePersist): T {
  const cloned = cloneJson(data)
  const entry: CacheEntry<T> = {
    data: cloned,
    updatedAt: Date.now(),
  }
  memoryStore.set(key, entry)
  if (persist === 'session') {
    writeSessionEntry(key, entry)
  }
  return cloneJson(cloned)
}

export function peekRequestCache<T>(
  key: string,
  ttlMs = 60_000,
  persist: RequestCachePersist = 'session',
): RequestCacheSnapshot<T> {
  const entry = resolveEntry<T>(key, persist)
  if (!entry) {
    return {
      data: null,
      updatedAt: null,
      ageMs: Number.POSITIVE_INFINITY,
      isFresh: false,
    }
  }

  const ageMs = Date.now() - entry.updatedAt
  return {
    data: cloneJson(entry.data),
    updatedAt: entry.updatedAt,
    ageMs,
    isFresh: ageMs <= ttlMs,
  }
}

export async function fetchRequestCache<T>(
  key: string,
  fetcher: () => Promise<T>,
  options: FetchRequestCacheOptions = {},
): Promise<T> {
  const {
    force = false,
    persist = 'session',
    signal,
    ttlMs = 60_000,
  } = options

  throwIfAborted(signal)

  const snapshot = peekRequestCache<T>(key, ttlMs, persist)
  if (!force && snapshot.data != null && snapshot.isFresh) {
    recordPerf('request-cache.hit', 'ok', 0, {
      key,
      ttlMs,
      ageMs: snapshot.ageMs,
    })
    return snapshot.data
  }

  const pending = inFlight.get(key) as Promise<T> | undefined
  if (pending) {
    recordPerf('request-cache.join', 'ok', 0, { key })
    return bindAbort(pending, signal)
  }

  const task = (async () => {
    const finish = startPerfSpan('request-cache.fill', {
      key,
      ttlMs,
      persist,
      force,
    })
    try {
      throwIfAborted(signal)
      const result = await fetcher()
      throwIfAborted(signal)
      const saved = saveEntry(key, result, persist)
      finish('ok')
      return saved
    } catch (error) {
      finish(error instanceof Error && error.name === 'AbortError' ? 'abort' : 'error')
      throw error
    }
  })()

  inFlight.set(key, task)
  void task.finally(() => {
    if (inFlight.get(key) === task) {
      inFlight.delete(key)
    }
  })
  return bindAbort(task, signal)
}

export function invalidateRequestCache(keyPrefix?: string): void {
  if (!keyPrefix) {
    memoryStore.clear()
    if (canUseSessionStorage()) {
      try {
        const keysToRemove: string[] = []
        for (let i = 0; i < window.sessionStorage.length; i += 1) {
          const key = window.sessionStorage.key(i)
          if (key && key.startsWith(SESSION_PREFIX)) {
            keysToRemove.push(key)
          }
        }
        keysToRemove.forEach((key) => window.sessionStorage.removeItem(key))
      } catch {
        // Ignore storage clear failures.
      }
    }
    return
  }

  for (const key of [...memoryStore.keys()]) {
    if (key.startsWith(keyPrefix)) {
      memoryStore.delete(key)
      removeSessionEntry(key)
    }
  }

  if (!canUseSessionStorage()) return
  try {
    const keysToRemove: string[] = []
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i)
      if (key && key.startsWith(SESSION_PREFIX) && key.slice(SESSION_PREFIX.length).startsWith(keyPrefix)) {
        keysToRemove.push(key)
      }
    }
    keysToRemove.forEach((key) => window.sessionStorage.removeItem(key))
  } catch {
    // Ignore storage clear failures.
  }
}
