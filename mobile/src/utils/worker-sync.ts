import { clearCache } from './cache'

const WORKER_ORDER_SYNC_EVENT = 'worker:orders-updated'
const WORKER_CACHE_KEYS = [
  'worker_workspace',
  'worker_workspace_support',
  'worker_workorders',
  'worker_support_workorders',
  'worker_messages',
  'worker_shared_hall',
] as const

export interface WorkerOrdersSyncPayload {
  reason: string
  ticketId?: string
  incidentId?: string
  timestamp: number
}

export function invalidateWorkerOrderCaches() {
  WORKER_CACHE_KEYS.forEach(key => clearCache(key))
}

export function emitWorkerOrdersUpdated(payload: Omit<WorkerOrdersSyncPayload, 'timestamp'>) {
  const eventPayload: WorkerOrdersSyncPayload = {
    ...payload,
    timestamp: Date.now(),
  }
  invalidateWorkerOrderCaches()
  uni.$emit(WORKER_ORDER_SYNC_EVENT, eventPayload)
}

export function subscribeWorkerOrdersUpdated(
  handler: (payload: WorkerOrdersSyncPayload) => void | Promise<void>,
) {
  const wrapped = (payload: WorkerOrdersSyncPayload) => {
    void handler(payload)
  }
  uni.$on(WORKER_ORDER_SYNC_EVENT, wrapped)
  return () => {
    uni.$off(WORKER_ORDER_SYNC_EVENT, wrapped)
  }
}
