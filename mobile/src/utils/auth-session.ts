type AuthResetHandler = () => void | Promise<void>

const authResetHandlers = new Set<AuthResetHandler>()

export function registerAuthResetHandler(handler: AuthResetHandler) {
  authResetHandlers.add(handler)
  return () => {
    authResetHandlers.delete(handler)
  }
}

export async function clearAuthRuntimeState() {
  const tasks = Array.from(authResetHandlers, (handler) => Promise.resolve().then(handler))
  if (!tasks.length) return
  await Promise.allSettled(tasks)
}
