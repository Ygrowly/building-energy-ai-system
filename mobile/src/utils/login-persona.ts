import type { UserRole } from '../constants/roles'

export type PersonaKey = 'repair' | 'ops' | 'user'

interface LoginPersonaCacheEntry {
  role: UserRole
  persona: PersonaKey
  updatedAt: number
}

type LoginPersonaCache = Record<string, LoginPersonaCacheEntry>

const STORAGE_KEY = 'login_persona_cache'
const CACHE_LIMIT = 24

export function normalizeLoginUsername(username: string): string {
  return username.trim().toLowerCase()
}

export function roleToPersona(role: UserRole): PersonaKey {
  if (role === 'ops') return 'repair'
  if (role === 'admin' || role === 'manager') return 'ops'
  return 'user'
}

function readCache(): LoginPersonaCache {
  const raw = uni.getStorageSync(STORAGE_KEY)
  if (!raw) return {}

  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    return parsed && typeof parsed === 'object' ? parsed as LoginPersonaCache : {}
  } catch {
    return {}
  }
}

function writeCache(cache: LoginPersonaCache) {
  uni.setStorageSync(STORAGE_KEY, JSON.stringify(cache))
}

function trimCache(cache: LoginPersonaCache): LoginPersonaCache {
  const entries = Object.entries(cache)
    .sort(([, a], [, b]) => b.updatedAt - a.updatedAt)
    .slice(0, CACHE_LIMIT)

  return Object.fromEntries(entries)
}

export function getCachedPersonaByUsername(username: string): LoginPersonaCacheEntry | null {
  const normalized = normalizeLoginUsername(username)
  if (!normalized) return null

  const cache = readCache()
  return cache[normalized] ?? null
}

export function rememberLoginPersona(username: string, role: UserRole) {
  const normalized = normalizeLoginUsername(username)
  if (!normalized) return

  const cache = readCache()
  cache[normalized] = {
    role,
    persona: roleToPersona(role),
    updatedAt: Date.now(),
  }

  writeCache(trimCache(cache))
}
