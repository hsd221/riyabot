/**
 * Bot 配置页面相关类型定义
 */

export interface BotConfig {
  platform: string
  qq_account: string | number
  nickname: string
  platforms: string[]
  alias_names: string[]
}

export interface PersonalityConfig {
  personality: string
  reply_style: string
  multiple_reply_style: string[]
  multiple_probability: number
  plan_style: string
  visual_style: string
  states: string[]
  state_probability: number
}

export interface TalkValueRule {
  target: string
  time: string
  value: number
}

export interface ChatConfig {
  talk_value: number
  mentioned_bot_reply: boolean
  at_bot_inevitable_reply: number
  max_context_size: number
  planner_smooth: number
  enable_talk_value_rules: boolean
  talk_value_rules: TalkValueRule[]
  plan_reply_log_max_per_chat: number
  llm_quote: boolean
}

export interface ExpressionConfig {
  learning_list: Array<[string, string, string, string]>
  expression_groups: Array<string[]>
  expression_self_reflect: boolean
  expression_manual_reflect: boolean
  manual_reflect_operator_id: string
  allow_reflect: string[]
  all_global_jargon: boolean
  enable_jargon_explanation: boolean
  jargon_mode: 'context' | 'planner'
  expression_checked_only: boolean
  expression_auto_check_interval: number
  expression_auto_check_count: number
  expression_auto_check_custom_criteria: string[]
}

export interface EmojiConfig {
  emoji_chance: number
  max_reg_num: number
  do_replace: boolean
  check_interval: number
  steal_emoji: boolean
  content_filtration: boolean
  filtration_prompt: string
}

export interface MemoryConfig {
  max_agent_iterations: number
  agent_timeout_seconds: number
  global_memory: boolean
  global_memory_blacklist: string[]
  planner_question: boolean
  sqlite_path: string
  qdrant_url: string
  qdrant_api_key?: string | null
  qdrant_local_path: string
  embedding_dimension: number
  collection_name_atoms: string
  collection_name_graph: string
  vector_batch_size: number
}

export interface ToolConfig {
  enable_tool: boolean
}

export interface VoiceConfig {
  enable_asr: boolean
}

export interface MessageReceiveConfig {
  ban_words: string[]
  ban_msgs_regex: string[]
}

export interface KeywordRule {
  keywords?: string[]
  regex?: string[]
  reaction: string
}

export interface KeywordReactionConfig {
  keyword_rules: KeywordRule[]
  regex_rules: KeywordRule[]
}

export interface ResponsePostProcessConfig {
  enable_response_post_process: boolean
}

export interface ChineseTypoConfig {
  enable: boolean
  error_rate: number
  min_freq: number
  tone_error_rate: number
  word_replace_rate: number
}

export interface ResponseSplitterConfig {
  enable: boolean
  max_length: number
  max_sentence_num: number
  enable_kaomoji_protection: boolean
  enable_overflow_return_all: boolean
}

export interface LogConfig {
  date_style: string
  log_level_style: string
  color_text: string
  log_level: string
  console_log_level: string
  file_log_level: string
  suppress_libraries: string[]
  library_log_levels: Record<string, string>
}

export interface DebugConfig {
  show_prompt: boolean
  show_replyer_prompt: boolean
  show_replyer_reasoning: boolean
  show_jargon_prompt: boolean
  show_memory_prompt: boolean
  show_planner_prompt: boolean
  show_lpmm_paragraph: boolean
}

export interface MaimMessageConfig {
  auth_token: string[]
  enable_api_server: boolean
  api_server_host: string
  api_server_port: number
  api_server_use_wss: boolean
  api_server_cert_file: string
  api_server_key_file: string
  api_server_allowed_api_keys: string[]
}

export interface TelemetryConfig {
  enable: boolean
}

export interface WebUIConfig {
  enabled: boolean
  mode: 'development' | 'production'
  anti_crawler_mode: 'false' | 'strict' | 'loose' | 'basic'
  allowed_ips: string
  trusted_proxies: string
  trust_xff: boolean
  secure_cookie: boolean
}

export interface ExperimentalConfig {
  private_plan_style: string
  chat_prompts: string[]
}

export interface DreamConfig {
  interval_minutes: number
  max_iterations: number
  first_delay_seconds: number
  dream_send: string
  dream_time_ranges: string[]
  dream_visible: boolean
}

/**
 * 所有配置的聚合类型
 */
export interface AllBotConfigs {
  botConfig: BotConfig | null
  personalityConfig: PersonalityConfig | null
  chatConfig: ChatConfig | null
  expressionConfig: ExpressionConfig | null
  emojiConfig: EmojiConfig | null
  memoryConfig: MemoryConfig | null
  toolConfig: ToolConfig | null
  voiceConfig: VoiceConfig | null
  messageReceiveConfig: MessageReceiveConfig | null
  keywordReactionConfig: KeywordReactionConfig | null
  responsePostProcessConfig: ResponsePostProcessConfig | null
  chineseTypoConfig: ChineseTypoConfig | null
  responseSplitterConfig: ResponseSplitterConfig | null
  logConfig: LogConfig | null
  debugConfig: DebugConfig | null
  maimMessageConfig: MaimMessageConfig | null
  telemetryConfig: TelemetryConfig | null
  webuiConfig: WebUIConfig | null
  experimentalConfig: ExperimentalConfig | null
  dreamConfig: DreamConfig | null
}

/**
 * 配置节名称到类型的映射
 */
export type ConfigSectionName = 
  | 'bot'
  | 'personality'
  | 'chat'
  | 'expression'
  | 'emoji'
  | 'memory'
  | 'tool'
  | 'voice'
  | 'message_receive'
  | 'keyword_reaction'
  | 'response_post_process'
  | 'chinese_typo'
  | 'response_splitter'
  | 'log'
  | 'debug'
  | 'maim_message'
  | 'telemetry'
  | 'webui'
  | 'experimental'
  | 'dream'
