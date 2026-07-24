import { AlertTriangle, BookOpen, ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { countHistoryCandidates } from '@/lib/chat-history-import-view'
import type { ChatHistoryCandidateKind, ChatHistoryImportTask } from '@/types/chat-history-import'
import {
  candidateKindLabels,
  candidateKindOrder,
  formatCandidateCount,
  getCandidateCatalogSummary,
} from './chat-history-candidate-catalog-model'
import { ChatHistoryCandidateRows } from './chat-history-candidate-catalog-view'
import { useChatHistoryCandidateCatalog } from './use-chat-history-candidate-catalog'

const PAGE_SIZE = 20

export function ChatHistoryCandidateCatalog({ task }: { task: ChatHistoryImportTask }) {
  const summary = getCandidateCatalogSummary(task)
  const runtimeCounts = countHistoryCandidates(task.result)
  const runtimeTotal = Object.values(runtimeCounts).reduce((sum, count) => sum + count, 0)
  const {
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
  } = useChatHistoryCandidateCatalog(task, PAGE_SIZE)
  const isFullScan = task.options.depth === 'full'
  let catalogStatus = '需要复核'
  if (error) catalogStatus = '目录不可用'
  else if (summary.complete) {
    catalogStatus = isFullScan ? '全量窗口已穷尽' : '已选窗口已穷尽'
  }

  return (
    <section aria-labelledby="candidate-catalog-title" className="mt-4">
      <div className="mb-2 flex items-center justify-between gap-3 px-1">
        <h3 id="candidate-catalog-title" className="ios-section-label px-0">
          完整候选目录
        </h3>
        <Badge variant={error || !summary.complete ? 'destructive' : 'secondary'}>
          {catalogStatus}
        </Badge>
      </div>
      <div className="ios-group overflow-hidden">
        <div className="flex items-start gap-3 border-b border-border/60 px-4 py-4">
          <BookOpen className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-[15px] font-medium">
              已发现 {formatCandidateCount(summary.total)} 条候选，运行时精选集合为{' '}
              {formatCandidateCount(runtimeTotal)} 条
            </p>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              {isFullScan
                ? '全量模式会遍历聊天文件中的每一个自然窗口；分页只限制单次传输，运行时写入上限也不会截断完整目录。'
                : '当前目录只覆盖本档位选中的窗口；若要遍历整份聊天文件，请使用全量模式。分页只限制单次传输，不限制已分析窗口中的候选总数。'}
            </p>
          </div>
        </div>
        {!summary.complete && (
          <Alert variant="destructive" className="m-3">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            <AlertDescription>
              {summary.incomplete_window_ids.length}{' '}
              个窗口没有确认穷尽，目录仍可浏览，但不应把它当成最终全量结果。
            </AlertDescription>
          </Alert>
        )}
        <RadioGroup
          value={kind}
          onValueChange={(value) => selectKind(value as ChatHistoryCandidateKind)}
          className="mx-3 mt-3 grid grid-cols-2 gap-1 rounded-[14px] bg-muted/60 p-1 sm:grid-cols-5"
          aria-label="候选类型"
        >
          {candidateKindOrder.map((item) => (
            <div key={item} className="relative min-w-0">
              <RadioGroupItem id={`candidate-kind-${item}`} value={item} className="peer sr-only" />
              <label
                htmlFor={`candidate-kind-${item}`}
                className="peer-data-[state=checked]:bg-white/88 inline-flex min-h-11 w-full cursor-pointer items-center justify-center gap-1.5 rounded-[11px] px-2 py-2 text-xs font-medium text-muted-foreground transition-[background-color,color,box-shadow,transform] duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] active:scale-[0.98] peer-focus-visible:ring-2 peer-focus-visible:ring-ring/35 peer-data-[state=checked]:text-foreground peer-data-[state=checked]:shadow-[0_1px_1px_rgba(255,255,255,0.82)_inset,0_2px_8px_rgba(0,0,0,0.05)] peer-data-[state=checked]:ring-1 peer-data-[state=checked]:ring-black/[0.035] motion-reduce:transition-none dark:peer-data-[state=checked]:bg-[rgb(72_72_74_/_0.96)] dark:peer-data-[state=checked]:ring-white/[0.06]"
              >
                <span className="truncate">{candidateKindLabels[item]}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {formatCandidateCount(summary.counts[item] ?? 0)}
                </span>
              </label>
            </div>
          ))}
        </RadioGroup>
        <div className="relative px-3 py-3">
          <Search
            className="pointer-events-none absolute left-6 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            id="chat-history-candidate-search"
            name="chat-history-candidate-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={`搜索${candidateKindLabels[kind]}`}
            aria-label={`搜索完整${candidateKindLabels[kind]}目录`}
            className="h-11 pl-9"
          />
        </div>
        {error && (
          <div
            className="bg-destructive/10 text-destructive mx-3 mb-3 rounded-[12px] px-3 py-2 text-[13px]"
            role="alert"
          >
            {error}
          </div>
        )}
        {!error &&
          (loading ? (
            <div className="space-y-2 px-4 pb-4" aria-busy="true" aria-label="正在加载候选目录">
              <div className="h-14 animate-pulse rounded-[12px] bg-muted/60 motion-reduce:animate-none" />
              <div className="h-14 animate-pulse rounded-[12px] bg-muted/60 motion-reduce:animate-none" />
            </div>
          ) : (
            <ChatHistoryCandidateRows kind={kind} candidates={candidates} />
          ))}
        <div className="flex items-center justify-between border-t border-border/60 px-4 py-3">
          <span className="text-[13px] text-muted-foreground">
            {error
              ? '无法读取候选页'
              : `第 ${pagination.page} / ${pagination.total_pages} 页 · 共 ${formatCandidateCount(
                  pagination.total_items
                )} 条`}
          </span>
          <div className="flex gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-11 w-11 p-0"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={Boolean(error) || loading || page <= 1}
              aria-label="上一页"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-11 w-11 p-0"
              onClick={() => setPage((current) => Math.min(pagination.total_pages, current + 1))}
              disabled={Boolean(error) || loading || page >= pagination.total_pages}
              aria-label="下一页"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}
