const AVATAR_STORAGE_PREFIX = 'avatar_'

function getAvatarStorageKey(userId?: string | null) {
  return `${AVATAR_STORAGE_PREFIX}${userId || 'guest'}`
}

export function getStoredAvatarUrl(userId?: string | null) {
  const storedValue = uni.getStorageSync(getAvatarStorageKey(userId))
  return typeof storedValue === 'string' ? storedValue : ''
}

export function setStoredAvatarUrl(userId: string | null | undefined, url: string) {
  uni.setStorageSync(getAvatarStorageKey(userId), url)
}
