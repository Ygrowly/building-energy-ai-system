/**
 * 统一请求封装
 * - 自动携带 Bearer Token
 * - 401 时自动用 refresh_token 续期 → 重试原请求
 * - 续期锁：防止多个并发 401 同时触发 refresh
 * - 统一错误提示
 */

const UNI_PLATFORM = process.env.UNI_PLATFORM || 'unknown'
const ENV_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').trim()
const IS_LOOPBACK_BASE_URL = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?(\/|$)/i.test(ENV_BASE_URL)

// H5 开发态可以走 Vite 代理；App/小程序开发态必须显式指向后端地址。
const BASE_URL = ENV_BASE_URL || (
  import.meta.env.DEV && UNI_PLATFORM === 'h5'
    ? ''
    : 'http://127.0.0.1:8000'
)

if (import.meta.env.DEV && UNI_PLATFORM !== 'h5' && !ENV_BASE_URL) {
  console.warn(
    `[api] 当前平台=${UNI_PLATFORM}，开发环境未设置 VITE_API_BASE_URL，` +
    '将回退到 http://127.0.0.1:8000。真机调试时请改成电脑局域网 IP。'
  )
}

if (import.meta.env.DEV && UNI_PLATFORM !== 'h5' && IS_LOOPBACK_BASE_URL) {
  console.warn(
    `[api] 当前平台=${UNI_PLATFORM}，VITE_API_BASE_URL=${ENV_BASE_URL} 指向回环地址。` +
    '真机调试时这会指向手机自身，不会连到电脑上的后端，请改成电脑局域网 IP。'
  )
}

function getToken(): string | null {
  return uni.getStorageSync('access_token') || null
}

function getRefreshToken(): string | null {
  return uni.getStorageSync('refresh_token') || null
}

function clearAuth() {
  uni.removeStorageSync('access_token')
  uni.removeStorageSync('refresh_token')
  uni.removeStorageSync('user_info')
}

let isRedirectingToLogin = false

function redirectToLogin() {
  clearAuth()
  if (isRedirectingToLogin) return
  isRedirectingToLogin = true
  uni.showToast({ title: '登录已过期，请重新登录', icon: 'none', duration: 2000 })
  setTimeout(() => {
    uni.reLaunch({ url: '/pages/login/index' })
    setTimeout(() => {
      isRedirectingToLogin = false
    }, 600)
  }, 0)
}

// ---- refresh token 锁 ----
let isRefreshing = false
let refreshSubscribers: Array<(token: string | null) => void> = []

function onTokenRefreshed(newToken: string | null) {
  refreshSubscribers.forEach(cb => cb(newToken))
  refreshSubscribers = []
}

function subscribeTokenRefresh(): Promise<string | null> {
  return new Promise(resolve => {
    refreshSubscribers.push(resolve)
  })
}

async function doRefresh(): Promise<string | null> {
  const rt = getRefreshToken()
  if (!rt) return null

  try {
    const res: any = await new Promise((resolve, reject) => {
      uni.request({
        url: BASE_URL + '/api/auth/refresh',
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: { refresh_token: rt },
        success: (r) => r.statusCode === 200 ? resolve(r.data) : reject(r),
        fail: reject,
      })
    })

    const newAccessToken = res.access_token
    const newRefreshToken = res.refresh_token
    uni.setStorageSync('access_token', newAccessToken)
    if (newRefreshToken) uni.setStorageSync('refresh_token', newRefreshToken)
    return newAccessToken
  } catch {
    return null
  }
}

export async function refreshAccessToken(): Promise<string | null> {
  return doRefresh()
}

// ---- 核心请求函数 ----

export interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  data?: unknown
  header?: Record<string, string>
  skipAuth?: boolean
}

async function doRequest<T>(options: RequestOptions, retried = false): Promise<T> {
  const token = getToken()
  if (!options.skipAuth && !token) {
    redirectToLogin()
    throw new Error('未登录或登录已过期')
  }
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.header || {}),
  }
  if (token && !options.skipAuth) {
    headers['Authorization'] = `Bearer ${token}`
  }

  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + options.url,
      method: (options.method || 'GET') as any,
      data: options.data,
      header: headers,
      success: async (res) => {
        // ---- 401 自动续期 ----
        if (res.statusCode === 401 && !options.skipAuth && !retried) {
          if (!isRefreshing) {
            isRefreshing = true
            const newToken = await doRefresh()
            isRefreshing = false

            if (newToken) {
              onTokenRefreshed(newToken)
              // 用新 token 重试原请求
              try {
                const result = await doRequest<T>(options, true)
                resolve(result)
              } catch (e) { reject(e) }
              return
            } else {
              onTokenRefreshed(null)
              redirectToLogin()
              reject(new Error('登录已过期'))
              return
            }
          } else {
            // 其他请求等待 refresh 完成
            const newToken = await subscribeTokenRefresh()
            if (newToken) {
              try {
                const result = await doRequest<T>(options, true)
                resolve(result)
              } catch (e) { reject(e) }
              return
            } else {
              redirectToLogin()
              reject(new Error('登录已过期'))
              return
            }
          }
        }

        if (res.statusCode === 401) {
          redirectToLogin()
          reject(new Error('未登录或登录已过期'))
          return
        }
        if (res.statusCode === 403) {
          uni.showToast({ title: '权限不足', icon: 'none' })
          reject(new Error('权限不足'))
          return
        }
        if (res.statusCode >= 400) {
          const msg = (res.data as any)?.detail || `请求失败 (${res.statusCode})`
          uni.showToast({ title: msg, icon: 'none', duration: 3000 })
          reject(new Error(msg))
          return
        }
        resolve(res.data as T)
      },
      fail(err) {
        uni.showToast({ title: '网络异常，请检查连接', icon: 'none' })
        reject(err)
      },
    })
  })
}

// ---- 便捷方法 ----

export function get<T = unknown>(url: string, params?: Record<string, unknown>): Promise<T> {
  let fullUrl = url
  if (params) {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join('&')
    if (qs) fullUrl += `?${qs}`
  }
  return doRequest<T>({ url: fullUrl, method: 'GET' })
}

export function post<T = unknown>(url: string, data?: unknown): Promise<T> {
  return doRequest<T>({ url, method: 'POST', data })
}

export function patch<T = unknown>(url: string, data?: unknown): Promise<T> {
  return doRequest<T>({ url, method: 'PATCH', data })
}

export { doRequest as request, BASE_URL }
