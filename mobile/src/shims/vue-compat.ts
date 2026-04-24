export * from 'vue/dist/vue.runtime.esm-bundler.js'

import { getCurrentInstance } from 'vue/dist/vue.runtime.esm-bundler.js'

export const isInSSRComponentSetup = false

type HookTarget = (ReturnType<typeof getCurrentInstance> & Record<string, unknown>) | null

export function injectHook(
  type: string,
  hook: (...args: unknown[]) => unknown,
  target: HookTarget = getCurrentInstance() as HookTarget,
  prepend = false,
) {
  if (!target) {
    return undefined
  }

  const existingHooks = target[type]
  const hooks = Array.isArray(existingHooks) ? existingHooks : []
  if (!Array.isArray(existingHooks)) {
    target[type] = hooks
  }

  const wrappedHook = (...args: unknown[]) => hook(...args)
  if (prepend) {
    hooks.unshift(wrappedHook)
  } else {
    hooks.push(wrappedHook)
  }

  return wrappedHook
}
