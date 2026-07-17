import { CheckCircle2, Clock3, MessageSquareText, MinusCircle } from 'lucide-react'

import type { DreamRunMessageData } from '../../types/memory'

interface DreamRunMessageListProps {
  messages: DreamRunMessageData[]
  total: number
  runType: string
}

const ROUTE_LABELS: Record<string, string> = {
  high: '高优先级',
  medium: '中优先级',
  low: '低优先级',
  skipped: '跳过',
}

const ROUTE_CLASSES: Record<string, string> = {
  high: 'bg-[rgb(255_45_85_/_0.12)] text-[rgb(184_31_58)] dark:bg-[rgb(255_55_95_/_0.18)] dark:text-[rgb(255_105_125)]',
  medium:
    'bg-[rgb(255_149_0_/_0.14)] text-[rgb(172_96_0)] dark:bg-[rgb(255_159_10_/_0.2)] dark:text-[rgb(255_159_10)]',
  low: 'bg-[rgb(0_122_255_/_0.12)] text-[rgb(0_84_166)] dark:bg-[rgb(10_132_255_/_0.18)] dark:text-[rgb(100_210_255)]',
  skipped: 'bg-muted text-muted-foreground',
}

function formatMessageTime(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  if (Number.isNaN(date.getTime())) return '消息时间未记录'

  return date.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatProcessedTime(value: string | null): string {
  if (!value) return '处理时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return date.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSignificance(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '未评分'
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`
}

function DreamRunMessageItem({ message }: { message: DreamRunMessageData }) {
  const retained = message.outcome === 'retained_as_candidate'
  const routeLabel = ROUTE_LABELS[message.route] ?? '路线未记录'

  return (
    <li className="rounded-[16px] border border-border/50 bg-muted/25 p-4 [contain-intrinsic-size:auto_300px] [content-visibility:auto] sm:p-5">
      <div className="flex min-w-0 items-start gap-3">
        <span className="ios-symbol ios-symbol-sm ios-symbol-blue mt-0.5" aria-hidden="true">
          <MessageSquareText className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="break-words text-[14px] font-semibold leading-5 text-foreground">
              {message.sender_name}
            </p>
            <span className="text-[12px] text-muted-foreground">·</span>
            <p className="break-words text-[12px] leading-4 text-muted-foreground">
              {message.conversation_name}
            </p>
          </div>
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
            {formatMessageTime(message.message_timestamp)}
          </p>
        </div>
      </div>

      <div className="mt-3 rounded-[13px] border border-border/40 bg-background/65 px-3 py-2.5">
        <p className="mb-1 text-[11px] font-medium leading-4 text-muted-foreground">原始消息</p>
        <p className="whitespace-pre-wrap break-words text-[14px] leading-6 text-foreground">
          {message.content}
        </p>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)_minmax(0,1.6fr)]">
        <div className="rounded-[12px] bg-background/55 px-3 py-2.5">
          <p className="text-[11px] leading-4 text-muted-foreground">显著性评分</p>
          <p className="mt-0.5 text-[14px] font-semibold tabular-nums">
            {formatSignificance(message.significance)}
          </p>
        </div>
        <div className="rounded-[12px] bg-background/55 px-3 py-2.5">
          <p className="mb-1.5 text-[11px] leading-4 text-muted-foreground">分诊决定</p>
          <span
            className={`inline-flex min-h-6 items-center rounded-full px-2.5 py-0.5 text-[12px] font-medium leading-4 ${
              ROUTE_CLASSES[message.route] ?? 'bg-muted text-muted-foreground'
            }`}
          >
            {routeLabel}
          </span>
        </div>
        <div className="rounded-[12px] bg-background/55 px-3 py-2.5">
          <div className="flex items-start gap-2">
            {retained ? (
              <CheckCircle2
                className="mt-0.5 h-4 w-4 shrink-0 text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]"
                aria-hidden="true"
              />
            ) : (
              <MinusCircle
                className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
            )}
            <div className="min-w-0">
              <p className="text-[12px] font-semibold leading-4">
                {retained ? '保留到候选池' : '未进入候选池'}
              </p>
              <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                {retained
                  ? '等待后续交叉验证，这一步不会直接写入长期记忆。'
                  : '本轮已结束对这条消息的处理，不再进入后续候选流程。'}
              </p>
            </div>
          </div>
        </div>
      </div>

      <p className="mt-3 inline-flex items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
        <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
        {formatProcessedTime(message.processed_at)}
      </p>
    </li>
  )
}

export function DreamRunMessageList({ messages, total, runType }: DreamRunMessageListProps) {
  if (messages.length === 0) {
    const memoryOnlyRun = runType === 'weekly' || runType === 'monthly'

    return (
      <div
        className="flex min-h-48 flex-col items-center justify-center px-4 py-10 text-center"
        role="status"
      >
        <span className="ios-symbol ios-symbol-purple mb-3" aria-hidden="true">
          <MessageSquareText className="h-5 w-5" />
        </span>
        <p className="text-[15px] font-semibold leading-5">
          {memoryOnlyRun ? '本轮没有直接处理原始消息' : '没有可展示的消息处理记录'}
        </p>
        <p className="mt-1.5 max-w-md text-[13px] leading-5 text-muted-foreground">
          {memoryOnlyRun
            ? '这次梦境执行的是记忆级维护，例如冲突仲裁、巩固、遗忘或洞见提炼。'
            : '这可能是一轮没有待分诊消息的运行，或该历史记录早于逐消息追踪功能。'}
        </p>
      </div>
    )
  }

  return (
    <section aria-label="逐条消息处理结果">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
        <p className="text-[13px] leading-5 text-muted-foreground">
          本次直接处理 <span className="font-semibold text-foreground">{total}</span> 条原始消息
        </p>
        {total > messages.length ? (
          <p className="text-[12px] leading-4 text-muted-foreground">
            当前显示前 {messages.length} 条
          </p>
        ) : null}
      </div>
      <ol className="space-y-3">
        {messages.map((message) => (
          <DreamRunMessageItem key={message.archive_id} message={message} />
        ))}
      </ol>
    </section>
  )
}
