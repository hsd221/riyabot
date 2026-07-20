import { ChevronRight, ScanSearch } from 'lucide-react'
import { Skeleton } from '../ui/skeleton'
import { cn } from '../../lib/utils'
import { formatTraceDuration, formatTraceOperation } from './model-trace-format'
import { ModelTraceStatusBadge } from './model-trace-status'
import type { ModelTraceSummary } from '../../types/model-trace'

function formatTraceTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function TraceListSkeleton() {
  return (
    <div className="divide-y divide-border/55" aria-busy="true" aria-label="加载模型请求追踪">
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className="space-y-3 px-4 py-4">
          <div className="flex items-center justify-between gap-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-6 w-14 rounded-full" />
          </div>
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3 w-2/5" />
        </div>
      ))}
    </div>
  )
}

export function ModelTraceList({
  traces,
  selectedId,
  loading,
  onSelect,
}: {
  traces: ModelTraceSummary[]
  selectedId: number | null
  loading: boolean
  onSelect: (traceId: number) => void
}) {
  if (loading) return <TraceListSkeleton />
  if (traces.length === 0) {
    return (
      <div className="flex min-h-[24rem] flex-col items-center justify-center gap-3 px-6 text-center">
        <span className="ios-symbol ios-symbol-md ios-symbol-gray" aria-hidden="true">
          <ScanSearch className="h-5 w-5" />
        </span>
        <div>
          <p className="text-[16px] font-semibold">暂无匹配记录</p>
          <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
            新的模型请求会出现在这里
          </p>
        </div>
      </div>
    )
  }

  return (
    <ul role="list" className="divide-y divide-border/55">
      {traces.map((trace) => {
        const selected = trace.id === selectedId
        const preview =
          trace.request_preview || trace.response_preview || trace.error_message || '无文本内容'
        return (
          <li key={trace.id}>
            <button
              type="button"
              aria-current={selected ? 'true' : undefined}
              onClick={() => onSelect(trace.id)}
              className={cn(
                'group relative flex min-h-[7.25rem] w-full items-start gap-3 px-4 py-3.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/35',
                selected
                  ? 'bg-[rgb(0_122_255_/_0.075)] dark:bg-[rgb(10_132_255_/_0.12)]'
                  : 'hover:bg-muted/45'
              )}
            >
              {selected && (
                <span className="absolute inset-y-3 left-0 w-1 rounded-r-full bg-primary" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-[14px] font-semibold text-foreground">
                    {trace.model_name}
                  </p>
                  <ModelTraceStatusBadge status={trace.status} />
                </div>
                <p className="mt-1.5 line-clamp-2 break-words text-[13px] leading-5 text-muted-foreground">
                  {preview}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-4 text-muted-foreground">
                  <span>{trace.request_type || 'unknown'}</span>
                  <span aria-hidden="true">·</span>
                  <span>{formatTraceOperation(trace.operation)}</span>
                  <span aria-hidden="true">·</span>
                  <span>{formatTraceDuration(trace.duration_ms)}</span>
                  <span aria-hidden="true">·</span>
                  <time dateTime={trace.started_at}>{formatTraceTime(trace.started_at)}</time>
                </div>
              </div>
              <ChevronRight
                className={cn(
                  'mt-1 h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform',
                  selected && 'translate-x-0.5 text-primary'
                )}
              />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
