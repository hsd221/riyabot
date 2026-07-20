import { fetchWithAuth, getAuthHeaders } from '@/lib/fetch-with-auth'

const API_BASE = '/api/webui/config'

export type AdapterRuntimeStatus = 'stopped' | 'starting' | 'listening' | 'connected' | 'error'

export interface AdapterIdentity {
  account_id: string
  nickname: string
}

export interface AdapterInstance {
  id: string
  type: 'onebot_v11'
  name: string
  platform: 'qq'
  status: AdapterRuntimeStatus
  started: boolean
  connected: boolean
  identity: AdapterIdentity | null
  connection: {
    host: string
    port: number
  }
  connected_at?: number | null
  last_event_at?: number | null
  last_error?: string | null
}

export interface ManagedAdapterConfig {
  napcat_server: {
    host: string
    port: number
    token: string
    heartbeat_interval: number
  }
  chat: {
    group_list_type: 'whitelist' | 'blacklist'
    group_list: number[]
    private_list_type: 'whitelist' | 'blacklist'
    private_list: number[]
    ban_user_id: number[]
    ban_qq_bot: boolean
    enable_poke: boolean
  }
  voice: {
    use_tts: boolean
  }
  forward: {
    image_threshold: number
  }
  debug: {
    level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
  }
}

interface AdapterInstancesResponse {
  success: boolean
  adapters?: AdapterInstance[]
  message?: string
  detail?: string
}

interface ManagedAdapterConfigResponse {
  success: boolean
  config?: ManagedAdapterConfig
  message?: string
  detail?: string
}

interface ConfigMessageResponse {
  success: boolean
  message?: string
  detail?: string
}

async function readJson<T>(response: Response, fallbackMessage: string): Promise<T> {
  const data = (await response.json().catch(() => null)) as T | null
  if (!response.ok || !data) {
    const errorData = data as { message?: string; detail?: string } | null
    throw new Error(errorData?.detail || errorData?.message || fallbackMessage)
  }
  return data
}

export async function getAdapterInstances(): Promise<AdapterInstance[]> {
  const response = await fetchWithAuth(`${API_BASE}/adapters`)
  const data = await readJson<AdapterInstancesResponse>(response, '读取平台实例失败')
  if (!data.success || !data.adapters) {
    throw new Error(data.detail || data.message || '读取平台实例失败')
  }
  return data.adapters
}

export async function getManagedAdapterConfig(adapterId: string): Promise<ManagedAdapterConfig> {
  const response = await fetchWithAuth(
    `${API_BASE}/adapters/${encodeURIComponent(adapterId)}/config`
  )
  const data = await readJson<ManagedAdapterConfigResponse>(response, '读取平台配置失败')
  if (!data.success || !data.config) {
    throw new Error(data.detail || data.message || '读取平台配置失败')
  }
  return data.config
}

export async function saveManagedAdapterConfig(
  adapterId: string,
  config: ManagedAdapterConfig
): Promise<void> {
  const response = await fetchWithAuth(
    `${API_BASE}/adapters/${encodeURIComponent(adapterId)}/config`,
    {
      method: 'PUT',
      headers: getAuthHeaders(),
      body: JSON.stringify(config),
    }
  )
  const data = await readJson<ConfigMessageResponse>(response, '保存平台配置失败')
  if (!data.success) {
    throw new Error(data.detail || data.message || '保存平台配置失败')
  }
}
