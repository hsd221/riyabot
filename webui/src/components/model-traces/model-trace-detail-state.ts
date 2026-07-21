import type { ModelTraceDetail } from '../../types/model-trace'

type ModelTraceDetailView =
  | { kind: 'detail'; detail: ModelTraceDetail }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'empty' }

export function resolveModelTraceDetailView({
  selectedId,
  detail,
  loading,
  error,
}: {
  selectedId: number | null
  detail: ModelTraceDetail | null
  loading: boolean
  error: string | null
}): ModelTraceDetailView {
  if (detail?.id === selectedId) return { kind: 'detail', detail }
  if (loading) return { kind: 'loading' }
  if (error) return { kind: 'error', message: error }
  return { kind: 'empty' }
}
