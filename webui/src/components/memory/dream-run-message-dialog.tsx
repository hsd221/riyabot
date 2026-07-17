import { useEffect, useState } from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchDreamRunMessages } from '@/lib/api/memory-api'
import type { DreamRunData, DreamRunMessageData } from '@/types/memory'
import { DreamRunMessageList } from './dream-run-message-details'
import { getDreamRunTypeLabel } from './dream-run-summary'

interface DreamRunMessageDialogProps {
  run: DreamRunData | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

function MessageListSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="正在加载消息处理详情">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="rounded-[16px] border border-border/50 bg-muted/25 p-4">
          <div className="flex items-center gap-3">
            <Skeleton className="h-8 w-8 shrink-0 rounded-[9px]" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
          <Skeleton className="mt-3 h-20 w-full rounded-[13px]" />
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <Skeleton className="h-16 rounded-[12px]" />
            <Skeleton className="h-16 rounded-[12px]" />
            <Skeleton className="h-16 rounded-[12px]" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function DreamRunMessageDialog({ run, open, onOpenChange }: DreamRunMessageDialogProps) {
  const [messages, setMessages] = useState<DreamRunMessageData[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(open && run !== null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const runId = run?.id
  const runType = run?.run_type ?? ''

  useEffect(() => {
    if (!open || runId === undefined) return

    const controller = new AbortController()
    setMessages([])
    setTotal(0)
    setError(null)
    setLoading(true)

    void fetchDreamRunMessages(runId, {
      limit: 200,
      offset: 0,
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return
        setMessages(data.items)
        setTotal(data.total)
      })
      .catch((requestError: unknown) => {
        if (controller.signal.aborted) return
        setError(requestError instanceof Error ? requestError.message : '获取梦境消息处理详情失败')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [open, reloadKey, runId])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[92dvh] max-h-[860px] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0 sm:h-[min(84vh,760px)] sm:max-w-3xl">
        <DialogHeader className="border-b border-border/55 px-5 pb-4 pt-5 sm:px-6 sm:pb-5 sm:pt-6">
          <DialogTitle>
            {run ? `${getDreamRunTypeLabel(run.run_type)} #${run.id} 的消息处理` : '梦境消息处理'}
          </DialogTitle>
          <DialogDescription>
            查看这次运行对每条原始消息做出的显著性评估、分诊决定和最终去向。
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="min-h-0">
          <div className="px-4 py-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:px-6 sm:py-5">
            {loading ? (
              <MessageListSkeleton />
            ) : error ? (
              <div
                className="flex min-h-56 flex-col items-center justify-center px-4 py-10 text-center"
                role="alert"
              >
                <AlertCircle className="text-destructive mb-3 h-9 w-9" aria-hidden="true" />
                <p className="text-[15px] font-semibold leading-5">加载消息处理详情失败</p>
                <p className="mt-1.5 max-w-md text-[13px] leading-5 text-muted-foreground">
                  {error}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => setReloadKey((key) => key + 1)}
                >
                  <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
                  重试
                </Button>
              </div>
            ) : (
              <DreamRunMessageList messages={messages} total={total} runType={runType} />
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
