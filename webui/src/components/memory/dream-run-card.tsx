import { Database, MessagesSquare, Route, Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { DreamRunDetailedContent, DreamRunResultIcon } from './dream-run-card-details'
import { PHASE_CLASSES, RUN_TYPE_CLASSES } from './dream-run-card-styles'
import {
  formatDreamRunDuration,
  getDreamRunStatusLabel,
  getDreamRunTypeLabel,
  parseDreamRunSummary,
  type DreamRunActivity,
} from './dream-run-summary'
import type { DreamRunData } from '@/types/memory'

interface DreamRunCardProps {
  run: DreamRunData
  variant?: 'compact' | 'detailed'
  onOpenDetails?: (run: DreamRunData) => void
}

function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'default'
  if (status === 'failed') return 'destructive'
  if (status === 'pending') return 'outline'
  return 'secondary'
}

function formatDateTime(value: string | null): string {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function CompactResults({
  activities,
  status,
}: {
  activities: DreamRunActivity[]
  status: string
}) {
  if (activities.length === 0) {
    return (
      <p className="mt-3 text-[13px] leading-5 text-muted-foreground" role="status">
        {status === 'running' ? '正在整理，完成后会列出实际改动' : '这条记录没有保存结果明细'}
      </p>
    )
  }

  return (
    <ul className="mt-3 space-y-1.5" aria-label={status === 'failed' ? '失败信息' : '本次结果'}>
      {activities.slice(0, 3).map((activity, index) => (
        <li
          key={`${activity.label}-${index}`}
          className="flex min-w-0 items-start gap-2 text-[13px]"
        >
          <span
            className={cn(
              'mt-0.5 shrink-0',
              status === 'failed'
                ? 'text-destructive'
                : 'text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
            )}
          >
            <DreamRunResultIcon status={status} />
          </span>
          <span className="min-w-0 break-words leading-5">
            <span className="font-medium text-foreground">{activity.label}</span>
            {activity.details.length > 0 && (
              <span className="text-muted-foreground"> · {activity.details.join(' · ')}</span>
            )}
          </span>
        </li>
      ))}
      {activities.length > 3 && (
        <li className="pl-6 text-[12px] leading-4 text-muted-foreground">
          另有 {activities.length - 3} 项结果
        </li>
      )}
    </ul>
  )
}

export function DreamRunCard({ run, variant = 'detailed', onOpenDetails }: DreamRunCardProps) {
  const parsed = parseDreamRunSummary(run.summary, run.run_type)
  const actionCount = parsed.phases.reduce((total, phase) => total + phase.actions.length, 0)
  const compact = variant === 'compact'
  const titleId = `dream-run-${run.id}-title`

  return (
    <article
      aria-labelledby={titleId}
      className={cn(
        compact
          ? 'rounded-[16px] border border-border/45 bg-muted/35 p-4'
          : 'ios-group overflow-hidden p-4 sm:p-5'
      )}
    >
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="ios-symbol ios-symbol-sm ios-symbol-purple mt-0.5" aria-hidden="true">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 id={titleId} className="text-[15px] font-semibold leading-5 text-foreground">
                {getDreamRunTypeLabel(run.run_type)}
              </h3>
              <Badge
                variant="secondary"
                className={RUN_TYPE_CLASSES[run.run_type] ?? 'bg-muted text-muted-foreground'}
              >
                #{run.id}
              </Badge>
              <Badge variant={getStatusVariant(run.status)}>
                {getDreamRunStatusLabel(run.status)}
              </Badge>
            </div>
            <p className="mt-1 text-[12px] leading-4 text-muted-foreground">
              {formatDateTime(run.start_time)} · 用时{' '}
              {formatDreamRunDuration(run.start_time, run.end_time, run.status)}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-start gap-2 pl-11 sm:items-end sm:pl-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] leading-4 text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Database className="h-3.5 w-3.5" aria-hidden="true" />
              处理 {run.atoms_processed ?? 0} 条记忆
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Route className="h-3.5 w-3.5" aria-hidden="true" />
              {actionCount} 项流程
            </span>
          </div>
          {onOpenDetails ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 rounded-full px-3 text-[12px]"
              aria-label={`查看${getDreamRunTypeLabel(run.run_type)} #${run.id} 的消息处理`}
              onClick={() => onOpenDetails(run)}
            >
              <MessagesSquare className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              查看消息处理
            </Button>
          ) : null}
        </div>
      </header>

      {compact ? (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-1.5" aria-label="梦境运行阶段">
            {parsed.phases.map((phase, index) => (
              <span key={phase.code} className="inline-flex items-center gap-1.5">
                {index > 0 && <span className="text-muted-foreground/50">→</span>}
                <span
                  className={cn(
                    'rounded-full px-2 py-0.5 text-[11px] font-semibold',
                    PHASE_CLASSES[phase.code]
                  )}
                >
                  {phase.code}
                </span>
                <span className="text-[12px] text-muted-foreground">{phase.title}</span>
              </span>
            ))}
          </div>
          <CompactResults activities={parsed.activities} status={run.status} />
        </>
      ) : (
        <DreamRunDetailedContent run={run} parsed={parsed} titleId={titleId} />
      )}
    </article>
  )
}
