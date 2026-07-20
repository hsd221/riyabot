// 设置向导相关类型定义
import type { LucideIcon } from 'lucide-react'

export interface SetupStep {
  id: string
  title: string
  description: string
  icon: LucideIcon
}

export interface AgreementDocument {
  title: string
  file_name: string
  hash: string
  confirmed: boolean
  environment_confirmed: boolean
  content: string
}

export interface AgreementStatus {
  agreement_required: boolean
  eula: AgreementDocument
  privacy: AgreementDocument
}

// 人格配置
export interface PersonalityConfig {
  personality: string
  reply_style: string
}

// 步骤3：表情包配置
export interface EmojiConfig {
  emoji_chance: number
  max_reg_num: number
  do_replace: boolean
  check_interval: number
  steal_emoji: boolean
  content_filtration: boolean
  filtration_prompt: string
  usage_scene_enabled: boolean
  usage_scene_context_messages: number
  usage_scene_max_scenes: number
  usage_scene_weight: number
  selection_candidate_count: number
}

// 步骤4：其他基础配置
export interface OtherBasicConfig {
  enable_tool: boolean
  all_global_jargon: boolean
}
