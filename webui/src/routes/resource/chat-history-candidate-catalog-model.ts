import { countHistoryCatalogCandidates } from '@/lib/chat-history-import-view'
import type {
  ChatHistoryCandidateCatalogSummary,
  ChatHistoryCandidateKind,
  ChatHistoryImportTask,
} from '@/types/chat-history-import'

export const candidateKindLabels: Record<ChatHistoryCandidateKind, string> = {
  expressions: '表达方式',
  behaviors: '行为模式',
  jargons: '群内黑话',
  memories: '聊天记忆',
  profiles: '成员画像',
}

export const candidateKindOrder: ChatHistoryCandidateKind[] = [
  'expressions',
  'behaviors',
  'jargons',
  'memories',
  'profiles',
]

const numberFormatter = new Intl.NumberFormat('zh-CN')

export function formatCandidateCount(value: number): string {
  return numberFormatter.format(value)
}

export function getCandidateCatalogSummary(
  task: ChatHistoryImportTask
): ChatHistoryCandidateCatalogSummary {
  const raw = task.result?.candidate_catalog
  if (raw && 'counts' in raw) return raw
  const counts = countHistoryCatalogCandidates(task.result)
  return {
    total: Object.values(counts).reduce((sum, count) => sum + count, 0),
    counts,
    complete: task.result?.candidate_catalog_complete ?? true,
    incomplete_window_ids: task.result?.incomplete_window_ids ?? [],
    storage: 'inline',
  }
}
