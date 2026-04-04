/**
 * 简单缓存：内存 + 本地存储
 * 页面切换时先显示缓存数据，再后台刷新；reLaunch 后也能尽量命中
 */

interface CacheEntry {
  data: any
  timestamp: number
}

const store: Record<string, CacheEntry> = {}
const DEFAULT_TTL = 2 * 60 * 1000 // 2 分钟
const STORAGE_PREFIX = '__mobile_cache__:'

function getStorageKey(key: string) {
  return `${STORAGE_PREFIX}${key}`
}

function clone<T>(data: T): T {
  return JSON.parse(JSON.stringify(data)) as T
}

function canUseStorage() {
  return typeof uni !== 'undefined'
    && typeof uni.getStorageSync === 'function'
    && typeof uni.setStorageSync === 'function'
}

function readStorageEntry(key: string): CacheEntry | null {
  if (!canUseStorage()) return null
  try {
    const raw = uni.getStorageSync(getStorageKey(key))
    if (!raw) return null
    const entry = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!entry || typeof entry.timestamp !== 'number') return null
    return entry as CacheEntry
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

/** 读缓存，过期返回 null */
export function getCache<T>(key: string, ttl = DEFAULT_TTL): T | null {
  let entry = store[key]

  if (!entry) {
    const storageEntry = readStorageEntry(key)
    if (storageEntry) {
      store[key] = storageEntry
      entry = storageEntry
    }
  }

  if (!entry) return null
  if (Date.now() - entry.timestamp > ttl) {
    delete store[key]
    removeStorageEntry(key)
    return null
  }
  return clone(entry.data as T)
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
