/**
 * 记忆系统 API 客户端
 */
import { fetchWithAuth } from '@/lib/fetch-with-auth'
import type {
  MemoryStats,
  AtomData,
  DreamRunData,
  DreamRunMessageData,
  InsightData,
  NoiseData,
} from '@/types/memory'

const API_BASE = '/api/webui/memory'

/**
 * 获取记忆系统统计数据
 */
export async function fetchMemoryStats(): Promise<MemoryStats> {
  const response = await fetchWithAuth(`${API_BASE}/stats`)

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取记忆统计数据失败')
  }

  const data = await response.json()
  return data
}

/**
 * 获取记忆原子列表
 */
export async function fetchMemoryAtoms(params?: {
  atom_type?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<{ items: AtomData[]; total: number }> {
  const queryParams = new URLSearchParams()

  if (params?.atom_type) queryParams.append('atom_type', params.atom_type)
  if (params?.status) queryParams.append('status', params.status)
  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.offset !== undefined) queryParams.append('offset', params.offset.toString())

  const qs = queryParams.toString()
  const response = await fetchWithAuth(`${API_BASE}/atoms${qs ? `?${qs}` : ''}`)

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取记忆原子列表失败')
  }

  const data = await response.json()
  return data
}

/**
 * 获取记忆原子详情
 */
export async function fetchMemoryAtomDetail(atomId: string): Promise<AtomData> {
  const response = await fetchWithAuth(`${API_BASE}/atoms/${atomId}`)

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取记忆原子详情失败')
  }

  const data = await response.json()
  return data.data
}

/**
 * 获取梦境运行列表
 */
export async function fetchDreamRuns(params?: {
  limit?: number
  offset?: number
}): Promise<{ items: DreamRunData[]; total: number }> {
  const queryParams = new URLSearchParams()

  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.offset !== undefined) queryParams.append('offset', params.offset.toString())

  const qs = queryParams.toString()
  const response = await fetchWithAuth(`${API_BASE}/dream-runs${qs ? `?${qs}` : ''}`)

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取梦境运行列表失败')
  }

  const data = await response.json()
  return data
}

/**
 * 获取单次梦境逐消息处理详情
 */
export async function fetchDreamRunMessages(
  runId: number,
  params?: {
    limit?: number
    offset?: number
    signal?: AbortSignal
  }
): Promise<{ items: DreamRunMessageData[]; total: number }> {
  const queryParams = new URLSearchParams()

  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.offset !== undefined) queryParams.append('offset', params.offset.toString())

  const qs = queryParams.toString()
  const response = await fetchWithAuth(
    `${API_BASE}/dream-runs/${runId}/messages${qs ? `?${qs}` : ''}`,
    { signal: params?.signal }
  )

  if (!response.ok) {
    let message = '获取梦境消息处理详情失败'
    try {
      const error = (await response.json()) as { detail?: string }
      message = error.detail || message
    } catch {
      // 非 JSON 错误响应沿用安全的通用提示。
    }
    throw new Error(message)
  }

  return (await response.json()) as { items: DreamRunMessageData[]; total: number }
}

/**
 * 获取洞见列表
 */
export async function fetchInsights(params?: {
  limit?: number
  offset?: number
}): Promise<{ items: InsightData[]; total: number }> {
  const queryParams = new URLSearchParams()

  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.offset !== undefined) queryParams.append('offset', params.offset.toString())

  const qs = queryParams.toString()
  const response = await fetchWithAuth(`${API_BASE}/insights${qs ? `?${qs}` : ''}`)

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取洞见列表失败')
  }

  const data = await response.json()
  return data
}

/**
 * 获取噪声池列表
 */
export async function fetchNoisePool(params?: {
  limit?: number
  offset?: number
}): Promise<{ items: NoiseData[]; total: number }> {
  const queryParams = new URLSearchParams()

  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.offset !== undefined) queryParams.append('offset', params.offset.toString())

  const qs = queryParams.toString()
  const response = await fetchWithAuth(`${API_BASE}/noise-pool${qs ? `?${qs}` : ''}`)

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取噪声池列表失败')
  }

  const data = await response.json()
  return data
}
