/**
 * 记忆系统相关类型定义
 */

/**
 * 记忆统计数据
 */
export interface MemoryStats {
  total_atoms: number
  active_atoms: number
  type_distribution: Record<string, number>
  dream_run_count: number
  insight_count: number
  noise_pool_count: number
}

/**
 * 记忆原子信息
 */
export interface AtomData {
  atom_id: string
  atom_type: string
  content: string
  importance: number
  confidence: number
  weight: number
  status: string
  source_scene: string | null
  created_at: string
  entities: string[] | null
}

/**
 * 梦境运行记录
 */
export interface DreamRunData {
  id: number
  run_type: string
  start_time: string | null
  end_time: string | null
  status: string
  atoms_processed: number | null
  atoms_created: number | null
  summary: string | null
}

/**
 * 单次梦境对一条原始消息的处理详情
 */
export interface DreamRunMessageData {
  archive_id: number
  message_id: string
  stream_id: string
  user_id: string
  platform: string
  sender_name: string
  conversation_name: string
  content: string
  message_timestamp: number
  chat_type: string
  route: string
  significance: number | null
  outcome: string
  processed_at: string | null
}

/**
 * 洞见信息
 */
export interface InsightData {
  id: number
  content: string
  source_atoms: string[] | null
  agent_name: string | null
  confidence: number | null
  created_at: string
}

/**
 * 噪声池条目
 */
export interface NoiseData {
  id: number
  content: string
  source_scene: string | null
  significance: number | null
  created_at: string
}

/**
 * 分页列表响应（通用）— 后端直接返回 { items, total }，无额外包装
 */
export interface PaginatedList<T> {
  items: T[]
  total: number
}
