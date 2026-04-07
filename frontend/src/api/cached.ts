import { apiFetch } from './http'
import {
  fetchRequestCache,
  invalidateRequestCache,
  peekRequestCache,
  type RequestCachePersist,
  type RequestCacheSnapshot,
} from '@/utils/requestCache'

interface CachedApiFetchOptions {
  force?: boolean
  persist?: RequestCachePersist
  ttlMs?: number
}

function getMethod(init?: RequestInit): string {
  return (init?.method ?? 'GET').toUpperCase()
}

function getCacheKey(path: string, init?: RequestInit): string {
  return `api:${getMethod(init)}:${path}`
}

export function peekCachedApi<T>(
  path: string,
  options: Omit<CachedApiFetchOptions, 'force'> = {},
): RequestCacheSnapshot<T> {
  return peekRequestCache<T>(
    getCacheKey(path),
    options.ttlMs ?? 60_000,
    options.persist ?? 'session',
  )
}

export async function cachedApiFetch<T>(
  path: string,
  init?: RequestInit,
  options: CachedApiFetchOptions = {},
): Promise<T> {
  if (getMethod(init) !== 'GET' || init?.body != null) {
    return apiFetch<T>(path, init)
  }

  return fetchRequestCache<T>(
    getCacheKey(path, init),
    () => apiFetch<T>(path, init),
    options,
  )
}

export function invalidateCachedApi(pathPrefix?: string): void {
  if (!pathPrefix) {
    invalidateRequestCache('api:')
    return
  }
  invalidateRequestCache(`api:GET:${pathPrefix}`)
}

export function clearCachedApi(): void {
  invalidateRequestCache('api:')
}
