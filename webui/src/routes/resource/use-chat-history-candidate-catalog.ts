import { useDeferredValue, useEffect, useState } from 'react'
import { listChatHistoryCandidates } from '@/lib/chat-history-import-api'
import type {
  ChatHistoryCandidateKind,
  ChatHistoryImportTask,
  ImportedHistoryCandidate,
} from '@/types/chat-history-import'

function emptyPagination(pageSize: number) {
  return { page: 1, page_size: pageSize, total_items: 0, total_pages: 1 }
}

export function useChatHistoryCandidateCatalog(task: ChatHistoryImportTask, pageSize: number) {
  const [kind, setKindState] = useState<ChatHistoryCandidateKind>('expressions')
  const [query, setQueryState] = useState('')
  const deferredQuery = useDeferredValue(query)
  const [page, setPage] = useState(1)
  const [candidates, setCandidates] = useState<ImportedHistoryCandidate[]>([])
  const [pagination, setPagination] = useState(() => emptyPagination(pageSize))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canLoad =
    Boolean(task.result) && ['completed', 'awaiting_profile_review'].includes(task.status)

  const selectKind = (nextKind: ChatHistoryCandidateKind) => {
    setKindState(nextKind)
    setPage(1)
  }

  const setQuery = (nextQuery: string) => {
    setQueryState(nextQuery)
    setPage(1)
  }

  useEffect(() => {
    if (!canLoad) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    listChatHistoryCandidates(
      task.import_id,
      { kind, query: deferredQuery, page, pageSize },
      controller.signal
    )
      .then((response) => {
        if (controller.signal.aborted) return
        setCandidates(response.data)
        setPagination(response.pagination)
      })
      .catch((reason) => {
        if (controller.signal.aborted) return
        setCandidates([])
        setPagination(emptyPagination(pageSize))
        setError(reason instanceof Error ? reason.message : '无法加载完整候选目录')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [canLoad, deferredQuery, kind, page, pageSize, task.import_id])

  return {
    kind,
    query,
    page,
    candidates,
    pagination,
    loading,
    error,
    selectKind,
    setQuery,
    setPage,
  }
}
