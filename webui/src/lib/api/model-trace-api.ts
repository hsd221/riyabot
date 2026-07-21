import { fetchWithAuth } from '../fetch-with-auth'
import type {
  ModelTraceDetail,
  ModelTraceListResponse,
  ModelTraceQuery,
  ModelTraceSummary,
} from '../../types/model-trace'

const API_BASE = '/api/webui/model-traces'

export function buildModelTraceMediaUrl(traceId: number, mediaId: string): string {
  return `${API_BASE}/${traceId}/media/${encodeURIComponent(mediaId)}`
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail || `请求失败 (${response.status})`
  } catch {
    return `请求失败 (${response.status})`
  }
}

export function buildModelTraceSearchParams(query: ModelTraceQuery): URLSearchParams {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
  })
  if (query.status) params.set('status', query.status)
  if (query.requestType) params.set('request_type', query.requestType)
  if (query.model) params.set('model', query.model)
  if (query.search?.trim()) params.set('search', query.search.trim())
  return params
}

export function mergeModelTraceUpdates(
  current: ModelTraceListResponse,
  updates: ModelTraceSummary[]
): ModelTraceListResponse {
  const updatesById = new Map(updates.map((trace) => [trace.id, trace]))
  let changed = false
  const data = current.data.map((trace) => {
    const update = updatesById.get(trace.id)
    if (
      !update ||
      (trace.status === update.status &&
        trace.completed_at === update.completed_at &&
        trace.duration_ms === update.duration_ms &&
        trace.response_preview === update.response_preview &&
        trace.error_type === update.error_type &&
        trace.error_message === update.error_message &&
        trace.status_code === update.status_code &&
        trace.prompt_tokens === update.prompt_tokens &&
        trace.completion_tokens === update.completion_tokens &&
        trace.total_tokens === update.total_tokens)
    ) {
      return trace
    }

    changed = true
    return {
      ...trace,
      status: update.status,
      completed_at: update.completed_at,
      duration_ms: update.duration_ms,
      response_preview: update.response_preview,
      error_type: update.error_type,
      error_message: update.error_message,
      status_code: update.status_code,
      prompt_tokens: update.prompt_tokens,
      completion_tokens: update.completion_tokens,
      total_tokens: update.total_tokens,
    }
  })

  return changed ? { ...current, data } : current
}

export async function fetchModelTraces(
  query: ModelTraceQuery,
  signal?: AbortSignal
): Promise<ModelTraceListResponse> {
  const params = buildModelTraceSearchParams(query)
  const response = await fetchWithAuth(`${API_BASE}?${params}`, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(await getErrorMessage(response))
  return (await response.json()) as ModelTraceListResponse
}

export async function fetchModelTraceDetail(
  traceId: number,
  signal?: AbortSignal
): Promise<ModelTraceDetail> {
  const response = await fetchWithAuth(`${API_BASE}/${traceId}`, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(await getErrorMessage(response))
  return (await response.json()) as ModelTraceDetail
}
