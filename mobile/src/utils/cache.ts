/**
 * 简单缓存：内存 + 本地存储
 * 页面切换时先显示缓存数据，再后台刷新；reLaunch 后也能尽量命中
 */

export interface CacheEntry<T = any> {
  data: T
  timestamp: number
}

const store: Record<string, CacheEntry> = {}
export const DEFAULT_CACHE_TTL = 2 * 60 * 1000 // 2 分钟
const STORAGE_PREFIX = '__mobile_cache__:'

function getStorageKey(key: string) {
  return `${STORAGE_PREFIX}${key}`
}

function clone<T>(data: T): T {
  if (data === undefined || data === null) return data
  return JSON.parse(JSON.stringify(data)) as T
}

function canUseStorage() {
  return typeof uni !== 'undefined'
    && typeof uni.getStorageSync === 'function'
    && typeof uni.setStorageSync === 'function'
}

function readStorageEntry<T = any>(key: string): CacheEntry<T> | null {
  if (!canUseStorage()) return null
  try {
    const raw = uni.getStorageSync(getStorageKey(key))
    if (!raw) return null
    const entry = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!entry || typeof entry.timestamp !== 'number') return null
    return entry as CacheEntry<T>
  } catch {
    return null
  }
}

function removeStorageEntry(key: string): void {
  if (!canUseStorage()) return
  try {
    uni.removeStorageSync(getStorageKey(key))
  } catch {
    // noop
  }
}

function getEntry<T = any>(key: string): CacheEntry<T> | null {
  let entry = store[key]

  if (!entry) {
    const storageEntry = readStorageEntry<T>(key)
    if (storageEntry) {
      store[key] = storageEntry
      entry = storageEntry
    }
  }

  return (entry as CacheEntry<T> | undefined) || null
}

export function getCacheEntry<T = any>(key: string, ttl = DEFAULT_CACHE_TTL): CacheEntry<T> | null {
  const entry = getEntry<T>(key)
  if (!entry) return null
  if (Date.now() - entry.timestamp > ttl) {
    delete store[key]
    removeStorageEntry(key)
    return null
  }
  return { data: clone(entry.data), timestamp: entry.timestamp }
}

/** 读缓存，过期返回 null */
export function getCache<T>(key: string, ttl = DEFAULT_CACHE_TTL): T | null {
  const entry = getCacheEntry<T>(key, ttl)
  if (!entry) return null
  return clone(entry.data as T)
}

export function getStaleCacheEntry<T = any>(key: string, maxAge = 24 * 60 * 60 * 1000): CacheEntry<T> | null {
  const entry = getEntry<T>(key)
  if (!entry) return null
  if (Date.now() - entry.timestamp > maxAge) {
    delete store[key]
    removeStorageEntry(key)
    return null
  }
  return { data: clone(entry.data), timestamp: entry.timestamp }
}

export function getStaleCache<T>(key: string, maxAge?: number): T | null {
  const entry = getStaleCacheEntry<T>(key, maxAge)
  if (!entry) return null
  return clone(entry.data as T)
}

export function clearCacheByPrefix(prefix: string): void {
  Object.keys(store)
    .filter(key => key.startsWith(prefix))
    .forEach(key => {
      delete store[key]
      removeStorageEntry(key)
    })

  if (!canUseStorage()) return
  try {
    const info = uni.getStorageInfoSync()
    const storagePrefix = getStorageKey(prefix)
    info.keys
      .filter(keyName => keyName.startsWith(storagePrefix))
      .forEach(keyName => uni.removeStorageSync(keyName))
  } catch {
    // noop
  }
}

/** 写缓存（深拷贝，防止引用污染） */
export function setCache(key: string, data: any): void {
  const entry = { data: clone(data), timestamp: Date.now() }
  store[key] = entry
  if (!canUseStorage()) return
  try {
    uni.setStorageSync(getStorageKey(key), entry)
  } catch {
    // noop
  }
}

/** 清缓存，不传 key 则清全部 */
export function clearCache(key?: string): void {
  if (key) {
    delete store[key]
    removeStorageEntry(key)
  } else {
    Object.keys(store).forEach(k => delete store[k])
    if (!canUseStorage()) return
    try {
      const info = uni.getStorageInfoSync()
      info.keys
        .filter(keyName => keyName.startsWith(STORAGE_PREFIX))
        .forEach(keyName => uni.removeStorageSync(keyName))
    } catch {
      // noop
    }
  }
}
