type IdleWindow = Window & {
  requestIdleCallback?: (
    callback: (deadline: { didTimeout: boolean; timeRemaining: () => number }) => void,
    options?: { timeout?: number },
  ) => number
  cancelIdleCallback?: (handle: number) => void
}

export function createDeferredTaskRunner() {
  let token = 0
  let timer = 0
  let idleHandle: number | null = null

  function clear() {
    token += 1
    if (timer) {
      window.clearTimeout(timer)
      timer = 0
    }

    const idleWindow = window as IdleWindow
    if (idleHandle != null && idleWindow.cancelIdleCallback) {
      idleWindow.cancelIdleCallback(idleHandle)
      idleHandle = null
    }
  }

  function schedule(
    tasks: Array<() => void>,
    onComplete?: () => void,
    options: { timeout?: number; delayMs?: number } = {},
  ) {
    clear()
    const runToken = token
    const idleWindow = window as IdleWindow

    const runAt = (index: number) => {
      if (runToken !== token) return
      if (index >= tasks.length) {
        onComplete?.()
        return
      }

      const invoke = () => {
        if (runToken !== token) return
        tasks[index]?.()
        runAt(index + 1)
      }

      if (idleWindow.requestIdleCallback) {
        idleHandle = idleWindow.requestIdleCallback(() => {
          idleHandle = null
          invoke()
        }, { timeout: options.timeout ?? 160 })
        return
      }

      timer = window.setTimeout(() => {
        timer = 0
        invoke()
      }, options.delayMs ?? 16)
    }

    runAt(0)
  }

  return {
    clear,
    schedule,
  }
}
