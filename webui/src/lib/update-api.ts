import { fetchWithAuth, getAuthHeaders } from './fetch-with-auth'

export type UpdateChannel = 'stable' | 'dev'
export type InstallationMode = 'source' | 'docker' | 'archive'

export type BuildIdentity = {
  version: string
  revision: string | null
  ref: string | null
  installation_mode: InstallationMode
  dirty: boolean
}

export type UpdateTarget = {
  ref: string
  revision: string
  summary: string
}

export type UpdateResult = {
  success: boolean
  code: string
  message: string
  completed_at: string
  target_revision: string | null
}

export type UpdateStatus = {
  channel: UpdateChannel
  current: BuildIdentity
  target: UpdateTarget | null
  update_available: boolean
  can_apply: boolean
  block_code: string | null
  block_message: string | null
  checked_at: string
  update_pending: boolean
  last_result: UpdateResult | null
}

type UpdatePreferencesResponse = {
  channel: UpdateChannel
}

export type CreateUpdateTaskResponse = {
  accepted: boolean
  target_revision: string
  message: string
}

export type UpdateResultResponse = {
  last_result: UpdateResult | null
}

const statusRequests = new Map<boolean, Promise<UpdateStatus>>()

async function parseResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const payload = (await response.json().catch(() => null)) as
    (T & { detail?: unknown; message?: unknown }) | null
  if (!response.ok) {
    const detail = payload?.detail ?? payload?.message
    throw new Error(typeof detail === 'string' ? detail : fallbackMessage)
  }
  if (payload === null) throw new Error(fallbackMessage)
  return payload
}

async function requestUpdateStatus(force: boolean): Promise<UpdateStatus> {
  const response = await fetchWithAuth(`/api/webui/updates/status?force=${String(force)}`, {
    method: 'GET',
    headers: getAuthHeaders(),
    cache: 'no-store',
  })
  return parseResponse<UpdateStatus>(response, '检查更新失败')
}

export function getUpdateStatus(force = false): Promise<UpdateStatus> {
  const activeRequest = statusRequests.get(force)
  if (activeRequest) return activeRequest

  const request = requestUpdateStatus(force).finally(() => {
    statusRequests.delete(force)
  })
  statusRequests.set(force, request)
  return request
}

export async function updateUpdatePreferences(
  channel: UpdateChannel
): Promise<UpdatePreferencesResponse> {
  const response = await fetchWithAuth('/api/webui/updates/preferences', {
    method: 'PATCH',
    headers: getAuthHeaders(),
    body: JSON.stringify({ channel }),
  })
  return parseResponse<UpdatePreferencesResponse>(response, '保存更新频道失败')
}

export async function getUpdateResult(): Promise<UpdateResultResponse> {
  const response = await fetchWithAuth('/api/webui/update-tasks/result', {
    method: 'GET',
    headers: getAuthHeaders(),
    cache: 'no-store',
  })
  return parseResponse<UpdateResultResponse>(response, '读取更新结果失败')
}

export async function createUpdateTask(
  expectedTargetRevision: string
): Promise<CreateUpdateTaskResponse> {
  const response = await fetchWithAuth('/api/webui/update-tasks', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ expected_target_revision: expectedTargetRevision }),
  })
  return parseResponse<CreateUpdateTaskResponse>(response, '创建更新任务失败')
}
