import { LoaderCircle, ShieldAlert, Sparkles, Trash2, UserRoundCheck } from 'lucide-react'
import { useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { cn } from '@/lib/utils'
import type { ChatHistoryImportTask, ChatHistoryProfileDecision } from '@/types/chat-history-import'

interface ChatHistoryProfileReviewProps {
  task: ChatHistoryImportTask
  submitting: boolean
  deleting: boolean
  onSubmit: (decisions: Record<string, ChatHistoryProfileDecision>) => void
  onDelete: () => void
}

function currentProfileFacts(task: ChatHistoryImportTask, profileId: string): string[] {
  const conflict = task.result?.profile_review?.conflicts.find(
    (item) => item.profile_id === profileId
  )
  if (!conflict) return []
  const current = conflict.current
  const values = [
    ...current.interests.map((value) => `兴趣：${value}`),
    ...Object.entries(current.preferences).map(([name, value]) => `${name}：${value}`),
    ...Object.entries(current.facts).map(([name, value]) => `${name}：${value}`),
    ...Object.entries(current.traits).map(
      ([name, value]) => `${name}：${Math.round(value * 100)}%`
    ),
  ]
  return values.slice(0, 6)
}

export function ChatHistoryProfileReview({
  task,
  submitting,
  deleting,
  onSubmit,
  onDelete,
}: ChatHistoryProfileReviewProps) {
  const review = task.result?.profile_review
  const [decisions, setDecisions] = useState<Record<string, ChatHistoryProfileDecision>>(
    review?.decisions ?? {}
  )
  if (!review) return null
  const complete = review.conflicts.every((conflict) => decisions[conflict.profile_id])

  return (
    <section aria-labelledby="profile-review-title" className="space-y-4">
      <div>
        <p id="profile-review-title" className="ios-section-label mb-2">
          人物画像确认
        </p>
        <Alert className="border-orange-500/25 bg-orange-500/[0.06]">
          <ShieldAlert className="h-4 w-4 text-orange-600 dark:text-orange-400" />
          <p className="mb-1 text-[15px] font-semibold leading-5 tracking-normal">
            学习结果尚未写入
          </p>
          <AlertDescription>
            发现 {review.conflicts.length} 个已有 QQ
            画像。保留现有会跳过该成员的全部导入画像；应用导入会处理该成员下方列出的全部候选，同名属性改为导入值，新属性直接新增，未列出的现有属性与身份可信度保持不变。全部确认后，表达、行为、黑话、记忆和画像才会开始写入。
          </AlertDescription>
        </Alert>
      </div>

      {review.conflicts.map((conflict) => {
        const displayName =
          conflict.current.cardname || conflict.current.nickname || conflict.subject_id
        const facts = currentProfileFacts(task, conflict.profile_id)
        return (
          <div key={conflict.profile_id} className="ios-group overflow-hidden">
            <div className="ios-row ios-row-plain items-start py-4">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-blue" aria-hidden="true">
                  <UserRoundCheck className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[16px] font-semibold">{displayName}</span>
                  <span className="block text-[12px] leading-5 text-muted-foreground">
                    {conflict.profile_id} · {conflict.current.verification_status}
                  </span>
                </span>
              </span>
              <Badge variant="outline">已有画像</Badge>
            </div>

            <div className="border-t border-border/55 px-4 py-4 sm:px-5">
              <p className="text-[12px] font-medium text-muted-foreground">当前画像摘要</p>
              {facts.length ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {facts.map((fact) => (
                    <span
                      key={fact}
                      className="rounded-[6px] bg-muted/70 px-2 py-1 text-[12px] leading-5"
                    >
                      {fact}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-[13px] text-muted-foreground">
                  当前画像没有可展示的结构化属性
                </p>
              )}
            </div>

            <div className="border-t border-border/55 px-4 py-4 sm:px-5">
              <p className="text-[12px] font-medium text-muted-foreground">本次准备写入</p>
              <div className="mt-2 divide-y divide-border/55">
                {conflict.imported.map((candidate, index) => (
                  <div
                    key={`${candidate.category}-${candidate.name}-${index}`}
                    className="flex min-w-0 items-start justify-between gap-4 py-2.5"
                  >
                    <span className="min-w-0">
                      <span className="block text-[14px] font-medium">{candidate.name}</span>
                      <span className="block break-words text-[13px] leading-5 text-muted-foreground">
                        {candidate.value}
                      </span>
                    </span>
                    <span className="shrink-0 text-right text-[12px] leading-5 text-muted-foreground">
                      {candidate.evidence_count} 条证据
                      <br />
                      {Math.round(candidate.confidence * 100)}% 置信度
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border-t border-border/55 p-3 sm:p-4">
              <RadioGroup
                value={decisions[conflict.profile_id]}
                onValueChange={(value) =>
                  setDecisions((current) => ({
                    ...current,
                    [conflict.profile_id]: value as ChatHistoryProfileDecision,
                  }))
                }
                className="grid grid-cols-2 gap-1 rounded-[10px] bg-muted/70 p-1"
                aria-label={`${displayName} 的画像处理方式`}
              >
                {[
                  { value: 'keep_existing', label: '保留现有画像' },
                  { value: 'apply_imported', label: '应用导入内容' },
                ].map((option) => (
                  <label
                    key={option.value}
                    className={cn(
                      'ios-touch relative flex min-h-11 cursor-pointer items-center justify-center rounded-[8px] px-2 text-center text-[13px] font-medium focus-within:ring-2 focus-within:ring-ring/35',
                      decisions[conflict.profile_id] === option.value &&
                        'bg-background shadow-[0_1px_3px_rgba(0,0,0,0.12)]'
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
            </div>
          </div>
        )
      })}

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Button variant="outline" onClick={onDelete} disabled={deleting || submitting}>
          <Trash2 className="mr-2 h-4 w-4" />
          删除任务
        </Button>
        <Button onClick={() => onSubmit(decisions)} disabled={!complete || submitting}>
          {submitting ? (
            <LoaderCircle className="ios-spin-slow mr-2 h-4 w-4" />
          ) : (
            <Sparkles className="mr-2 h-4 w-4" />
          )}
          确认并写入
        </Button>
      </div>
    </section>
  )
}
