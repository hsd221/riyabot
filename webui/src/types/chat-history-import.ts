export type ChatHistoryImportStatus =
  'analyzing' | 'ready' | 'running' | 'completed' | 'failed' | 'cancelled'

export type ChatHistoryLearningDepth = 'fast' | 'balanced' | 'deep'

export interface ImportedChat {
  name: string
  source_id: string
  chat_type: string
  self_user_id: string
}

export interface ImportedParticipant {
  source_id: string
  name: string
  card: string
  message_count: number
  is_bot: boolean
}

export interface ChatHistoryAnalysis {
  source_format: string
  chat: ImportedChat
  total_messages: number
  retained_messages: number
  filtered_messages: number
  noise_counts: Record<string, number>
  participants: ImportedParticipant[]
  start_timestamp: number | null
  end_timestamp: number | null
  total_window_count: number
}

export interface ChatHistoryImportProgress {
  stage: string
  current: number
  total: number
}

export interface ImportedExpressionCandidate {
  situation: string
  style: string
  evidence_ids: string[]
  confidence: number
}

export interface ImportedBehaviorCandidate {
  actor_type: string
  learning_type: string
  action: string
  outcome: string
  evidence_ids: string[]
  confidence: number
}

export interface ImportedJargonCandidate {
  content: string
  meaning: string
  evidence_ids: string[]
  confidence: number
}

export interface ImportedMemoryCandidate {
  atom_type: string
  content: string
  subject_id: string
  evidence_ids: string[]
  confidence: number
  importance: number
}

export interface ImportedProfileCandidate {
  subject_id: string
  category: string
  name: string
  value: string
  evidence_ids: string[]
  confidence: number
}

export interface HistoryEnrichmentStoreResult {
  memories_created: number
  profiles_created: number
  profiles_updated: number
  profiles_skipped: number
  write_failures: number
}

export interface ChatHistoryLearningResult {
  candidates: {
    expressions: ImportedExpressionCandidate[]
    behaviors: ImportedBehaviorCandidate[]
    jargons: ImportedJargonCandidate[]
    memories?: ImportedMemoryCandidate[]
    profiles?: ImportedProfileCandidate[]
  }
  total_window_count?: number
  selected_window_count?: number
  selected_window_ids?: string[]
  model_call_count?: number
  store_result?: {
    created: Record<string, number>
    updated: Record<string, number>
  } | null
  enrichment_store_result?: HistoryEnrichmentStoreResult | null
}

export interface ChatHistoryImportTask {
  import_id: string
  source_name: string
  source_size: number
  status: ChatHistoryImportStatus
  chat_id: string | null
  analysis: ChatHistoryAnalysis | null
  estimated_model_calls: Record<ChatHistoryLearningDepth, number>
  progress: ChatHistoryImportProgress
  options: {
    depth?: ChatHistoryLearningDepth
    participant_ids?: string[]
    extract_memories?: boolean
    update_profiles?: boolean
  }
  result: ChatHistoryLearningResult | null
  error_message: string | null
  created_at: number
  updated_at: number
  started_at: number | null
  completed_at: number | null
}

export interface ChatHistoryImportListResponse {
  success: boolean
  data: ChatHistoryImportTask[]
}

export interface ChatHistoryImportStartRequest {
  depth: ChatHistoryLearningDepth
  participant_ids: string[]
  extract_memories: boolean
  update_profiles: boolean
}

export interface ChatHistoryImportDeleteResponse {
  success: boolean
  message: string
}
