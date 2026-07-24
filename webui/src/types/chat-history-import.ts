export type ChatHistoryImportStatus =
  | 'analyzing'
  | 'ready'
  | 'running'
  | 'awaiting_profile_review'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type ChatHistoryLearningDepth = 'fast' | 'balanced' | 'deep' | 'full'

export type ChatHistoryParticipantScope =
  { mode: 'all'; excluded_ids: string[] } | { mode: 'custom'; included_ids: string[] }

export type ChatHistoryProfileDecision = 'keep_existing' | 'apply_imported'

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
  participant_count: number
  eligible_participant_count: number
  start_timestamp: number | null
  end_timestamp: number | null
  total_window_count: number
  estimated_model_call_note: string
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

export interface ExistingProfileSummary {
  profile_id: string
  nickname: string
  cardname: string
  verification_status: string
  interests: string[]
  preferences: Record<string, string>
  facts: Record<string, string>
  traits: Record<string, number>
}

export interface ImportedProfileConflictCandidate {
  category: string
  name: string
  value: string
  evidence_count: number
  confidence: number
}

export interface ChatHistoryProfileConflict {
  profile_id: string
  subject_id: string
  current: ExistingProfileSummary
  imported: ImportedProfileConflictCandidate[]
}

export interface ChatHistoryProfileReview {
  conflicts: ChatHistoryProfileConflict[]
  decisions: Record<string, ChatHistoryProfileDecision> | null
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
  continuation_window_ids?: string[]
  model_call_count?: number
  store_result?: {
    created: Record<string, number>
    updated: Record<string, number>
  } | null
  enrichment_store_result?: HistoryEnrichmentStoreResult | null
  profile_review?: ChatHistoryProfileReview
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
    participant_scope?: ChatHistoryParticipantScope
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
  participant_ids?: string[]
  participant_scope: ChatHistoryParticipantScope
  extract_memories: boolean
  update_profiles: boolean
}

export interface ChatHistoryParticipantListResponse {
  data: ImportedParticipant[]
  pagination: {
    page: number
    page_size: number
    total_items: number
    total_pages: number
  }
}

export interface ChatHistoryProfileDecisionRequest {
  decisions: Record<string, ChatHistoryProfileDecision>
}

export interface ChatHistoryImportDeleteResponse {
  success: boolean
  message: string
}
