/**
 * 行为学习相关类型定义
 */

export type BehaviorActorType = 'other_user' | 'group_collective' | 'maibot_self'
export type BehaviorLearningType = 'observed_behavior' | 'self_reflection'

/**
 * 行为模式信息
 */
export interface BehaviorPattern {
  id: number
  chat_id: string
  actor_type: BehaviorActorType
  learning_type: BehaviorLearningType
  action: string
  outcome: string
  source_text: string | null
  source_ids: string[]
  count: number
  score: number
  enabled: boolean
  selected_count: number
  last_selected_time: number | null
  last_active_time: number
  create_date: number | null
}

/**
 * 聊天信息
 */
export interface BehaviorChatInfo {
  chat_id: string
  chat_name: string
  platform: string | null
  is_group: boolean
}

export interface BehaviorListResponse {
  success: boolean
  total: number
  page: number
  page_size: number
  data: BehaviorPattern[]
}

export interface BehaviorDetailResponse {
  success: boolean
  data: BehaviorPattern
}

export interface BehaviorCreateRequest {
  chat_id: string
  actor_type: BehaviorActorType
  learning_type: BehaviorLearningType
  action: string
  outcome: string
  source_text?: string
  source_ids?: string[]
  count?: number
  score?: number
  enabled?: boolean
}

export interface BehaviorUpdateRequest {
  chat_id?: string
  actor_type?: BehaviorActorType
  learning_type?: BehaviorLearningType
  action?: string
  outcome?: string
  source_text?: string
  source_ids?: string[]
  count?: number
  score?: number
  enabled?: boolean
}

export interface BehaviorCreateResponse {
  success: boolean
  message: string
  data: BehaviorPattern
}

export interface BehaviorUpdateResponse {
  success: boolean
  message: string
  data?: BehaviorPattern
}

export interface BehaviorDeleteResponse {
  success: boolean
  message: string
}

export interface BehaviorStats {
  total: number
  enabled: number
  disabled: number
  recent_7days: number
  chat_count: number
  top_chats: Record<string, number>
  actor_type_counts: Record<BehaviorActorType, number>
  learning_type_counts: Record<BehaviorLearningType, number>
}

export interface BehaviorStatsResponse {
  success: boolean
  data: BehaviorStats
}

export interface BehaviorChatListResponse {
  success: boolean
  data: BehaviorChatInfo[]
}
