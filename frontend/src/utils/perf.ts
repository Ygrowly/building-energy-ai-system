export type PerfStatus = 'ok' | 'error' | 'abort'

export interface PerfEntry {
  name: string
  status: PerfStatus
  durationMs: number
  recordedAt: string
  detail?: Record<string, unknown>
}

declare global {
  interface Window {
    __CM_PERF__?: PerfEntry[]
  }
}

const PERF_BUFFER_LIMIT = 200

function canUsePerf(): boolean {
  return typeof window !== 'undefined' && typeof performance !== 'undefined'
}

function nowMs(): number {
  return canUsePerf() ? performance.now() : Date.now()
}

function toMessage(error: unknown): string | undefined {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return undefined
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

export function createAbortError(): Error {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('The operation was aborted.', 'AbortError')
  }

  const error = new Error('The operation was aborted.')
  error.name = 'AbortError'
  return error
}

export function recordPerf(
  name: string,
  status: PerfStatus,
  durationMs: number,
  detail?: Record<string, unknown>,
): void {
  if (!canUsePerf()) return

  const entry: PerfEntry = {
    name,
    status,
    durationMs,
    recordedAt: new Date().toISOString(),
    detail,
  }

  const bucket = window.__CM_PERF__ ?? (window.__CM_PERF__ = [])
  bucket.push(entry)
  if (bucket.length > PERF_BUFFER_LIMIT) {
    bucket.splice(0, bucket.length - PERF_BUFFER_LIMIT)
  }

  window.dispatchEvent(new CustomEvent('cm:perf', { detail: entry }))

  if (import.meta.env.DEV) {
    // Keep perf traces visible in devtools without spamming production logs.
    console.debug('[perf]', name, `${durationMs.toFixed(1)}ms`, status, detail ?? {})
  }
}

export function startPerfSpan(
  name: string,
  detail?: Record<string, unknown>,
): (status?: PerfStatus, extra?: Record<string, unknown>) => number {
  const startedAt = nowMs()
  let finished = false

  return (status = 'ok', extra) => {
    if (finished) {
      return 0
    }
    finished = true

    const durationMs = nowMs() - startedAt
    recordPerf(name, status, durationMs, {
      ...(detail ?? {}),
      ...(extra ?? {}),
    })
    return durationMs
  }
}

export async function measurePerf<T>(
  name: string,
  runner: () => Promise<T>,
  detail?: Record<string, unknown>,
): Promise<T> {
  const finish = startPerfSpan(name, detail)
  try {
    const result = await runner()
    finish('ok')
    return result
  } catch (error) {
    finish(isAbortError(error) ? 'abort' : 'error', {
      message: toMessage(error),
    })
    throw error
  }
}
