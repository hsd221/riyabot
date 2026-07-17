import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { DreamRunData } from '@/types/memory'
import { PHASE_CLASSES } from './dream-run-card-styles'
import type { ParsedDreamRunSummary } from './dream-run-summary'

interface DreamRunDetailedContentProps {
  run: DreamRunData
  parsed: ParsedDreamRunSummary
  titleId: string
}

export function DreamRunResultIcon({ status }: { status: string }) {
  if (status === 'failed') return <AlertTriangle className="h-4 w-4" aria-hidden="true" />
  if (status === 'running') {
    return (
      <LoaderCircle
        className="h-4 w-4 animate-spin motion-reduce:animate-none"
        aria-hidden="true"
      />
    )
  }
  return <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
}

export function DreamRunDetailedContent({ run, parsed, titleId }: DreamRunDetailedContentProps) {
  return (
    <div className="mt-5 space-y-5 border-t border-border/45 pt-5">
      <section aria-labelledby={`${titleId}-workflow`}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h4 id={`${titleId}-workflow`} className="text-[13px] font-semibold leading-5">
            整理流程
          </h4>
          <span className="text-[12px] text-muted-foreground">N2 → N3 → REM</span>
        </div>
        <ol className="grid gap-2 lg:grid-cols-3">
          {parsed.phases.map((phase) => (
            <li key={phase.code} className="rounded-[14px] border border-border/45 bg-muted/30 p-3">
              <div className="flex items-start gap-2.5">
                <span
                  className={cn(
                    'rounded-full px-2 py-0.5 text-[11px] font-semibold',
                    PHASE_CLASSES[phase.code]
                  )}
                >
                  {phase.code}
                </span>
                <div className="min-w-0">
                  <p className="text-[13px] font-semibold leading-5">{phase.title}</p>
                  <p className="text-[11px] leading-4 text-muted-foreground">{phase.description}</p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {phase.actions.map((action) => (
                  <span
                    key={action}
                    className="rounded-full border border-border/45 bg-background/70 px-2 py-1 text-[11px] leading-4 text-muted-foreground"
                  >
                    {action}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby={`${titleId}-results`}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h4 id={`${titleId}-results`} className="text-[13px] font-semibold leading-5">
            {run.status === 'failed' ? '失败信息' : '本次结果'}
          </h4>
          <span className="text-[12px] text-muted-foreground">
            {parsed.activities.length} 项记录
          </span>
        </div>
        {parsed.activities.length > 0 ? (
          <ul className="grid gap-2 sm:grid-cols-2">
            {parsed.activities.map((activity, index) => (
              <li
                key={`${activity.label}-${index}`}
                className="flex items-start gap-2.5 rounded-[13px] border border-border/40 bg-background/55 p-3"
              >
                <span
                  className={cn(
                    'mt-0.5 shrink-0',
                    run.status === 'failed'
                      ? 'text-destructive'
                      : 'text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
                  )}
                >
                  <DreamRunResultIcon status={run.status} />
                </span>
                <div className="min-w-0">
                  <p className="break-words text-[13px] font-medium leading-5 text-foreground">
                    {activity.label}
                  </p>
                  {activity.details.length > 0 ? (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {activity.details.map((detail) => (
                        <span
                          key={detail}
                          className="max-w-full break-all rounded-full bg-muted/70 px-2 py-0.5 text-[11px] leading-4 text-muted-foreground"
                        >
                          {detail}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div
            className="flex items-center gap-2.5 rounded-[13px] border border-dashed border-border/55 bg-muted/20 p-3 text-[13px] text-muted-foreground"
            role="status"
          >
            {run.status === 'running' ? (
              <LoaderCircle
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
            ) : (
              <Clock3 className="h-4 w-4" aria-hidden="true" />
            )}
            {run.status === 'running'
              ? '正在执行梦境维护，完成后会在这里列出实际改动。'
              : '流程已结束，但这条历史记录没有保存结果明细。'}
          </div>
        )}
      </section>
    </div>
  )
}
