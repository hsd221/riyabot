import { Check, ChevronLeft, ChevronRight, LoaderCircle, Search, Users } from 'lucide-react'
import { useDeferredValue, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ScrollArea } from '@/components/ui/scroll-area'
import { listChatHistoryParticipants } from '@/lib/chat-history-import-api'
import { cn } from '@/lib/utils'
import type { ChatHistoryParticipantScope, ImportedParticipant } from '@/types/chat-history-import'

const PAGE_SIZE = 30
const MAX_OVERRIDES = 200

interface ParticipantPickerProps {
  importId: string
  participantCount: number
  scope: ChatHistoryParticipantScope
  onChange: (scope: ChatHistoryParticipantScope) => void
}

function participantName(participant: ImportedParticipant): string {
  return participant.card || participant.name || participant.source_id
}

function scopeSummary(scope: ChatHistoryParticipantScope, participantCount: number): string {
  if (scope.mode === 'custom') return `已选择 ${scope.included_ids.length} 人`
  if (scope.excluded_ids.length)
    return `全部 ${participantCount} 人，排除 ${scope.excluded_ids.length} 人`
  return `全部有效成员，共 ${participantCount} 人`
}

export function ChatHistoryParticipantPicker({
  importId,
  participantCount,
  scope,
  onChange,
}: ParticipantPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query)
  const [page, setPage] = useState(1)
  const [participants, setParticipants] = useState<ImportedParticipant[]>([])
  const [totalPages, setTotalPages] = useState(1)
  const [totalItems, setTotalItems] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    listChatHistoryParticipants(
      importId,
      { query: deferredQuery, page, pageSize: PAGE_SIZE },
      controller.signal
    )
      .then((response) => {
        setParticipants(response.data)
        setTotalPages(response.pagination.total_pages)
        setTotalItems(response.pagination.total_items)
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return
        setError(requestError instanceof Error ? requestError.message : '无法加载参与者')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [deferredQuery, importId, open, page])

  const isSelected = (participantId: string) =>
    scope.mode === 'all'
      ? !scope.excluded_ids.includes(participantId)
      : scope.included_ids.includes(participantId)

  const toggleParticipant = (participantId: string, checked: boolean) => {
    if (scope.mode === 'all') {
      const excluded = new Set(scope.excluded_ids)
      if (checked) excluded.delete(participantId)
      else if (excluded.size < MAX_OVERRIDES) excluded.add(participantId)
      onChange({ mode: 'all', excluded_ids: Array.from(excluded) })
      return
    }
    const included = new Set(scope.included_ids)
    if (checked && included.size < MAX_OVERRIDES) included.add(participantId)
    else if (!checked) included.delete(participantId)
    onChange({ mode: 'custom', included_ids: Array.from(included) })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button type="button" className="ios-row ios-touch w-full text-left">
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-blue" aria-hidden="true">
              <Users className="h-4 w-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-[16px] leading-6">参与学习的成员</span>
              <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                {scopeSummary(scope, participantCount)}
              </span>
            </span>
          </span>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button>
      </DialogTrigger>
      <DialogContent className="flex max-h-[88dvh] min-h-[min(680px,88dvh)] flex-col gap-4 overflow-hidden sm:max-w-2xl [&>.ios-dialog-close]:h-11 [&>.ios-dialog-close]:w-11">
        <DialogHeader>
          <DialogTitle>选择参与学习的成员</DialogTitle>
          <DialogDescription>
            未选成员的消息仍作为对话上下文，但不会成为表达、行为、黑话、记忆或画像证据。
          </DialogDescription>
        </DialogHeader>

        <RadioGroup
          value={scope.mode}
          onValueChange={(mode) =>
            onChange(
              mode === 'all'
                ? { mode: 'all', excluded_ids: [] }
                : { mode: 'custom', included_ids: [] }
            )
          }
          className="grid grid-cols-2 gap-1 rounded-[10px] bg-muted/70 p-1"
          aria-label="成员选择方式"
        >
          {[
            { value: 'all', label: '全部成员' },
            { value: 'custom', label: '自定义' },
          ].map((option) => (
            <label
              key={option.value}
              className={cn(
                'ios-touch relative flex min-h-11 cursor-pointer items-center justify-center rounded-[8px] px-3 text-[14px] font-medium focus-within:ring-2 focus-within:ring-ring/35',
                scope.mode === option.value && 'bg-background shadow-[0_1px_3px_rgba(0,0,0,0.12)]'
              )}
            >
              <RadioGroupItem
                value={option.value}
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              />
              {option.label}
            </label>
          ))}
        </RadioGroup>

        <div className="relative">
          <Search
            className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setPage(1)
            }}
            className="pl-11"
            placeholder="搜索昵称、群名片或 QQ 号"
            aria-label="搜索参与者"
          />
        </div>

        <ScrollArea className="min-h-0 flex-1 rounded-[8px] border border-border/60 bg-background/45">
          <div role="list" aria-busy={loading}>
            {participants.map((participant) => {
              const selected = isSelected(participant.source_id)
              const selectionLimitReached =
                scope.mode === 'all'
                  ? selected && scope.excluded_ids.length >= MAX_OVERRIDES
                  : !selected && scope.included_ids.length >= MAX_OVERRIDES
              return (
                <label
                  key={participant.source_id}
                  className={cn(
                    'ios-row ios-touch min-h-[64px] cursor-pointer bg-transparent',
                    (participant.is_bot || selectionLimitReached) && 'cursor-not-allowed opacity-60'
                  )}
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <Checkbox
                      checked={selected && !participant.is_bot}
                      disabled={participant.is_bot || selectionLimitReached}
                      onCheckedChange={(checked) =>
                        toggleParticipant(participant.source_id, checked === true)
                      }
                      aria-label={`选择 ${participantName(participant)}`}
                    />
                    <span className="min-w-0">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[15px] font-medium">
                          {participantName(participant)}
                        </span>
                        {participant.is_bot ? <Badge variant="outline">本 Bot</Badge> : null}
                      </span>
                      <span className="block truncate text-[12px] leading-5 text-muted-foreground">
                        {participant.source_id} ·{' '}
                        {participant.message_count.toLocaleString('zh-CN')} 条消息
                      </span>
                    </span>
                  </span>
                  {selected && !participant.is_bot ? (
                    <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                  ) : null}
                </label>
              )
            })}
            {loading ? (
              <div className="flex min-h-32 items-center justify-center text-muted-foreground">
                <LoaderCircle className="ios-spin-slow h-5 w-5" aria-hidden="true" />
                <span className="ml-2 text-sm">正在加载成员</span>
              </div>
            ) : null}
            {!loading && !error && participants.length === 0 ? (
              <p className="px-4 py-12 text-center text-sm text-muted-foreground">没有匹配的成员</p>
            ) : null}
            {error ? (
              <p role="alert" className="text-destructive px-4 py-12 text-center text-sm">
                {error}
              </p>
            ) : null}
          </div>
        </ScrollArea>

        <DialogFooter className="items-center sm:justify-between">
          <span className="min-w-0 text-[13px] leading-5 text-muted-foreground">
            <span className="block">
              {deferredQuery ? `找到 ${totalItems} 人` : scopeSummary(scope, participantCount)}
            </span>
            <span className="block">自定义选择或排除最多 {MAX_OVERRIDES} 人</span>
          </span>
          <span className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-11 w-11"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1 || loading}
              aria-label="上一页成员"
              title="上一页"
            >
              <ChevronLeft />
            </Button>
            <span className="min-w-16 text-center text-[13px] tabular-nums text-muted-foreground">
              {page} / {totalPages}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-11 w-11"
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              disabled={page >= totalPages || loading}
              aria-label="下一页成员"
              title="下一页"
            >
              <ChevronRight />
            </Button>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
