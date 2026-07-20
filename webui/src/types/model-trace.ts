export type ModelTraceStatus = 'running' | 'success' | 'error'

interface ModelTraceMediaBase {
  media_id: string
  size_bytes: number
}

export type ModelTraceMedia =
  | (ModelTraceMediaBase & {
      kind: 'image'
      format: 'png' | 'jpeg' | 'gif' | 'webp'
      mime_type: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp'
    })
  | (ModelTraceMediaBase & {
      kind: 'audio'
      format: 'wav' | 'mp3' | 'ogg' | 'flac' | 'mp4' | 'webm' | 'amr'
      mime_type:
        | 'audio/wav'
        | 'audio/mpeg'
        | 'audio/ogg'
        | 'audio/flac'
        | 'audio/mp4'
        | 'audio/webm'
        | 'audio/amr'
    })

export interface ModelTraceSummary {
  id: number
  request_type: string
  operation: string
  model_name: string
  model_identifier: string
  provider_name: string
  attempt: number
  status: ModelTraceStatus
  started_at: string
  completed_at: string | null
  duration_ms: number | null
  request_preview: string
  response_preview: string
  error_type: string | null
  error_message: string | null
  status_code: number | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface ModelTraceDetail extends ModelTraceSummary {
  request_payload: unknown
  response_payload: unknown | null
  media: ModelTraceMedia[]
}

export interface ModelTraceListResponse {
  data: ModelTraceSummary[]
  pagination: {
    page: number
    page_size: number
    total_items: number
    total_pages: number
  }
  filter_options: {
    request_types: string[]
    models: string[]
  }
}

export interface ModelTraceQuery {
  page: number
  pageSize: number
  status?: ModelTraceStatus
  requestType?: string
  model?: string
  search?: string
}
