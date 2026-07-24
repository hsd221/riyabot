import type {
  ChatHistoryImportStatus,
  ChatHistoryLearningResult,
} from '@/types/chat-history-import'

export interface ChatHistoryCandidateCounts {
  expressions: number
  behaviors: number
  jargons: number
  memories: number
  profiles: number
}

export function countHistoryCandidates(
  result: ChatHistoryLearningResult | null | undefined
): ChatHistoryCandidateCounts {
  const candidates = result?.candidates
  return {
    expressions: candidates?.expressions?.length ?? 0,
    behaviors: candidates?.behaviors?.length ?? 0,
    jargons: candidates?.jargons?.length ?? 0,
    memories: candidates?.memories?.length ?? 0,
    profiles: candidates?.profiles?.length ?? 0,
  }
}

export function countHistoryCatalogCandidates(
  result: ChatHistoryLearningResult | null | undefined
): ChatHistoryCandidateCounts {
  const catalog = result?.candidate_catalog
  if (catalog && 'counts' in catalog) {
    return {
      expressions: catalog.counts.expressions ?? 0,
      behaviors: catalog.counts.behaviors ?? 0,
      jargons: catalog.counts.jargons ?? 0,
      memories: catalog.counts.memories ?? 0,
      profiles: catalog.counts.profiles ?? 0,
    }
  }
  if (catalog) {
    return {
      expressions: catalog.expressions?.length ?? 0,
      behaviors: catalog.behaviors?.length ?? 0,
      jargons: catalog.jargons?.length ?? 0,
      memories: catalog.memories?.length ?? 0,
      profiles: catalog.profiles?.length ?? 0,
    }
  }
  return countHistoryCandidates(result)
}

export function chatHistoryProgressPercent(
  status: ChatHistoryImportStatus,
  stage: string,
  current: number,
  total: number
): number {
  if (status === 'completed') return 100
  if (status === 'ready') return 0

  const localProgress = Math.min(1, Math.max(0, current) / Math.max(1, total))
  if (stage === 'extracting') return 2 + Math.round(localProgress * 76)
  if (stage === 'consolidating') return 80 + Math.round(localProgress * 10)
  if (stage === 'storing_catalog') return 91 + Math.round(localProgress * 2)
  if (stage === 'storing') return 94 + Math.round(localProgress * 2)
  if (stage === 'storing_enrichment') return 96 + Math.round(localProgress * 3)
  return status === 'running' ? 2 : 0
}

export function canCancelChatHistoryImport(
  status: ChatHistoryImportStatus,
  stage: string
): boolean {
  return (
    status === 'running' &&
    stage !== 'storing_catalog' &&
    stage !== 'storing' &&
    stage !== 'storing_enrichment'
  )
}
