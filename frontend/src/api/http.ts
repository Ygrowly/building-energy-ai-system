/**
 * REST API 工具函数。
 * - 自动附加 Authorization: Bearer <token> 请求头
 * - 遇到 401 时自动尝试 refresh，成功后重试原请求一次
 * - 若 refresh 也失败，触发 onUnauthorized（跳转登录页）
 *
 * 使用 setAuthProvider() 在 main.ts 中注入 auth 能力，
 * 避免与 authStore 产生循环依赖。
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

// ── 注入接口（由 main.ts 在 Pinia 初始化后调用）──────────
interface AuthProvider {
  getAccessToken: () => string | null
  refreshToken: () => Promise<void>
  onUnauthorized: () => void
}

let _auth: AuthProvider = {
  getAccessToken: () => null,
  refreshToken: async () => { throw new Error('no_auth') },
  onUnauthorized: () => {},
}

export function setAuthProvider(provider: AuthProvider) {
  _auth = provider
}

// ── 并发 refresh 锁 ────────────────────────────────────────
// 关键：若同时有多个请求都收到 401，只允许发出一次 refresh 请求。
// 其余请求共享同一个 Promise，等待同一次刷新完成。
// 若不加此锁，并发 refresh 会触发 token rotation，第 2、3 次
// 请求拿着已被吊销的旧 RT 去刷新，后端会判定为重放攻击并清除所有 token。
let _refreshingPromise: Promise<void> | null = null

// ── 核心请求函数 ──────────────────────────────────────────
export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await _doFetch(path, init)

  if (res.status === 401) {
    // 多个并发请求同时 401 时，复用同一个 refresh Promise
    if (!_refreshingPromise) {
      _refreshingPromise = _auth.refreshToken().finally(() => {
        _refreshingPromise = null
      })
    }
    try {
      await _refreshingPromise
    } catch {
      _auth.onUnauthorized()
      throw new Error('登录已过期，请重新登录')
    }
    // 用刷新后的新 token 重试原请求
    const retryRes = await _doFetch(path, init)
    if (retryRes.status === 401) {
      _auth.onUnauthorized()
      throw new Error('登录已过期，请重新登录')
    }
    if (!retryRes.ok) await _throwFromResponse(retryRes)
    return retryRes.json() as Promise<T>
  }

  if (!res.ok) await _throwFromResponse(res)
  return res.json() as Promise<T>
}

function _doFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = _auth.getAccessToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  return fetch(`${API_BASE}${path}`, { ...init, headers })
}

async function _throwFromResponse(res: Response): Promise<never> {
  const data = await res.json().catch(() => ({}))
  const msg = (data as { detail?: string }).detail ?? `HTTP ${res.status}`
  throw new Error(msg)
}
