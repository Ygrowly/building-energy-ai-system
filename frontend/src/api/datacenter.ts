/**
 * 数据中心 API 调用层。
 *
 * - 数据集（CSV/Excel）：上传、列表、详情、删除、AI 分析（SSE）
 * - 知识库文档（PDF/Word）：上传、列表、删除、解析（RAGFlow 代理）
 *
 * 文件上传使用原生 fetch + Authorization 头（不设 Content-Type，让浏览器自动添加 multipart boundary）。
 */

import { apiFetch } from './http'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

// ── 内部：带 auth 的 multipart 上传 ─────────────────────────────
async function _uploadFile(path: string, formData: FormData): Promise<unknown> {
  // 动态获取 token，避免循环依赖
  const { useAuthStore } = await import('@/stores/authStore')
  const token = useAuthStore().accessToken

  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const msg = (data as { detail?: string }).detail ?? `HTTP ${res.status}`
    throw new Error(msg)
  }
  return res.json()
}

// ══════════════════════════════════════════════════════════════
// 类型定义
// ══════════════════════════════════════════════════════════════

export interface ColumnInfo {
  name: string
  dtype: string
  null_count: number
  unique_count: number
}

export interface ColumnStats {
  min: number | null
  max: number | null
  mean: number | null
  std: number | null
  median: number | null
}

export interface DatasetSummary {
  id: string
  original_name: string
  file_type: string
  row_count: number
  column_count: number
  uploaded_at: string
}

export interface DatasetDetail extends DatasetSummary {
  columns: ColumnInfo[]
  stats: Record<string, ColumnStats>
  sample_rows: Record<string, unknown>[]
}

export interface RagDocument {
  id: string
  name: string
  size: number
  run: string         // unstart | running | CANCEL | done | fail
  progress: number
  create_time: number | string
  update_time: number | string
  [key: string]: unknown
}

export interface RagDocumentStatus {
  id: string
  run: string
  chunk_count: number
  progress: number
  progress_msg: unknown[]
  update_time?: number | string | null
}

export interface RagDocumentListResponse {
  code: number
  data: {
    docs: RagDocument[]
    total: number
  }
}

export interface RagUploadResponse {
  code?: number
  data?: unknown
  id?: string
  [key: string]: unknown
}

// ══════════════════════════════════════════════════════════════
// 数据集 API
// ══════════════════════════════════════════════════════════════

/** 上传 CSV/Excel 数据集文件，返回解析后的详情。 */
export async function uploadDataset(file: File): Promise<DatasetDetail> {
  const form = new FormData()
  form.append('file', file)
  return _uploadFile('/api/datacenter/datasets/upload', form) as Promise<DatasetDetail>
}

/** 获取当前用户的数据集列表。 */
export async function listDatasets(): Promise<DatasetSummary[]> {
  return apiFetch<DatasetSummary[]>('/api/datacenter/datasets')
}

/** 获取数据集详情（含列信息、统计、样本数据）。 */
export async function getDataset(id: string): Promise<DatasetDetail> {
  return apiFetch<DatasetDetail>(`/api/datacenter/datasets/${id}`)
}

/** 删除数据集。 */
export async function deleteDataset(id: string): Promise<void> {
  await apiFetch(`/api/datacenter/datasets/${id}`, { method: 'DELETE' })
}

/**
 * 对数据集发起 AI 分析（SSE 流式）。
 * @param id 数据集 ID
 * @param onChunk 每次收到文本块时的回调
 * @param onDone  流结束时的回调
 * @param onError 出错时的回调
 */
export async function analyzeDataset(
  id: string,
  onChunk: (text: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
): Promise<void> {
  const { useAuthStore } = await import('@/stores/authStore')
  const token = useAuthStore().accessToken
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}/api/datacenter/datasets/${id}/analyze`, {
    method: 'POST',
    headers,
  })
  if (!res.ok || !res.body) {
    onError(`请求失败：HTTP ${res.status}`)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6).trim()
      if (payload === '[DONE]') { onDone(); return }
      try {
        const obj = JSON.parse(payload) as { text?: string; error?: string }
        if (obj.error) { onError(obj.error); return }
        if (obj.text) onChunk(obj.text)
      } catch { /* ignore malformed chunk */ }
    }
  }
  onDone()
}

// ══════════════════════════════════════════════════════════════
// 知识库文档 API（代理 RAGFlow）
// ══════════════════════════════════════════════════════════════

/** 上传 PDF/Word/TXT 文档到 RAGFlow 知识库。 */
export async function uploadDocument(file: File): Promise<RagUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  return _uploadFile('/api/datacenter/documents/upload', form) as Promise<RagUploadResponse>
}

/** 获取 RAGFlow 知识库文档列表。 */
export async function listDocuments(page = 1, pageSize = 30): Promise<RagDocumentListResponse> {
  return apiFetch<RagDocumentListResponse>(
    `/api/datacenter/documents?page=${page}&page_size=${pageSize}`,
  )
}

/** 删除 RAGFlow 知识库中的文档。 */
export async function deleteDocument(docId: string): Promise<void> {
  await apiFetch(`/api/datacenter/documents/${docId}`, { method: 'DELETE' })
}

/** 查询 RAGFlow 文档解析状态（轮询用）。 */
export async function getDocumentStatus(docId: string): Promise<RagDocumentStatus> {
  return apiFetch<RagDocumentStatus>(`/api/datacenter/documents/${docId}/status`)
}

/** 触发 RAGFlow 文档解析（向量化）。 */
export async function parseDocument(docId: string): Promise<void> {
  await apiFetch(`/api/datacenter/documents/${docId}/parse`, { method: 'POST' })
}
