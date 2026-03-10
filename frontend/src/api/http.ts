/**
 * REST API 工具函数。
 * 所有请求走 Vite 代理（/api → http://localhost:8000），
 * 也兼容通过 VITE_API_BASE 直接访问的场景。
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}
