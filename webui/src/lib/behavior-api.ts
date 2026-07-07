/**
 * 行为学习管理 API
 */
import { fetchWithAuth } from '@/lib/fetch-with-auth'
import type {
  BehaviorActorType,
  BehaviorChatListResponse,
  BehaviorCreateRequest,
  BehaviorCreateResponse,
  BehaviorDeleteResponse,
  BehaviorDetailResponse,
  BehaviorLearningType,
  BehaviorListResponse,
  BehaviorStatsResponse,
  BehaviorUpdateRequest,
  BehaviorUpdateResponse,
} from '@/types/behavior'

const API_BASE = '/api/webui/behavior'

async function parseError(response: Response, fallback: string): Promise<Error> {
  try {
    const error = await response.json()
    return new Error(error.detail || fallback)
  } catch {
    return new Error(fallback)
  }
}

export async function getBehaviorChatList(): Promise<BehaviorChatListResponse> {
  const response = await fetchWithAuth(`${API_BASE}/chats`, {})

  if (!response.ok) {
    throw await parseError(response, '获取聊天列表失败')
  }

  return response.json()
}

export async function getBehaviorList(params: {
  page?: number
  page_size?: number
  search?: string
  chat_id?: string
  enabled?: boolean
  actor_type?: BehaviorActorType
  learning_type?: BehaviorLearningType
}): Promise<BehaviorListResponse> {
  const queryParams = new URLSearchParams()

  if (params.page) queryParams.append('page', params.page.toString())
  if (params.page_size) queryParams.append('page_size', params.page_size.toString())
  if (params.search) queryParams.append('search', params.search)
  if (params.chat_id) queryParams.append('chat_id', params.chat_id)
  if (params.enabled !== undefined) queryParams.append('enabled', params.enabled ? 'true' : 'false')
  if (params.actor_type) queryParams.append('actor_type', params.actor_type)
  if (params.learning_type) queryParams.append('learning_type', params.learning_type)

  const response = await fetchWithAuth(`${API_BASE}/list?${queryParams}`, {})

  if (!response.ok) {
    throw await parseError(response, '获取行为模式列表失败')
  }

  return response.json()
}

export async function getBehaviorDetail(behaviorId: number): Promise<BehaviorDetailResponse> {
  const response = await fetchWithAuth(`${API_BASE}/${behaviorId}`, {})

  if (!response.ok) {
    throw await parseError(response, '获取行为模式详情失败')
  }

  return response.json()
}

export async function createBehavior(data: BehaviorCreateRequest): Promise<BehaviorCreateResponse> {
  const response = await fetchWithAuth(`${API_BASE}/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })

  if (!response.ok) {
    throw await parseError(response, '创建行为模式失败')
  }

  return response.json()
}

export async function updateBehavior(
  behaviorId: number,
  data: BehaviorUpdateRequest
): Promise<BehaviorUpdateResponse> {
  const response = await fetchWithAuth(`${API_BASE}/${behaviorId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

  if (!response.ok) {
    throw await parseError(response, '更新行为模式失败')
  }

  return response.json()
}

export async function deleteBehavior(behaviorId: number): Promise<BehaviorDeleteResponse> {
  const response = await fetchWithAuth(`${API_BASE}/${behaviorId}`, {
    method: 'DELETE',
  })

  if (!response.ok) {
    throw await parseError(response, '删除行为模式失败')
  }

  return response.json()
}

export async function batchDeleteBehaviors(behaviorIds: number[]): Promise<BehaviorDeleteResponse> {
  const response = await fetchWithAuth(`${API_BASE}/batch/delete`, {
    method: 'POST',
    body: JSON.stringify({ ids: behaviorIds }),
  })

  if (!response.ok) {
    throw await parseError(response, '批量删除行为模式失败')
  }

  return response.json()
}

export async function getBehaviorStats(): Promise<BehaviorStatsResponse> {
  const response = await fetchWithAuth(`${API_BASE}/stats/summary`, {})

  if (!response.ok) {
    throw await parseError(response, '获取行为模式统计失败')
  }

  return response.json()
}
