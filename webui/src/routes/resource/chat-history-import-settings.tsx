import { LoaderCircle, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type {
  ChatHistoryImportTask,
  ChatHistoryLearningDepth,
  ImportedParticipant,
} from '@/types/chat-history-import'

const depthOptions: Array<{
  value: ChatHistoryLearningDepth
  label: string
  description: string
}> = [
  { value: 'fast', label: '快速', description: '覆盖关键时段，适合先试跑' },
  { value: 'balanced', label: '均衡', description: '兼顾时间跨度与主要成员' },
  { value: 'deep', label: '深入', description: '扩大窗口覆盖，模型调用更多' },
]

interface ChatHistoryImportSettingsProps {
  task: ChatHistoryImportTask
  depth: ChatHistoryLearningDepth
  participantIds: Set<string>
  extractMemories: boolean
  updateProfiles: boolean
  starting: boolean
  deleting: boolean
  onDepthChange: (depth: ChatHistoryLearningDepth) => void
  onParticipantsChange: (participantIds: Set<string>) => void
  onExtractMemoriesChange: (enabled: boolean) => void
  onUpdateProfilesChange: (enabled: boolean) => void
  onStart: () => void
  onDelete: () => void
}

function participantName(participant: ImportedParticipant): string {
  return participant.card || participant.name || participant.source_id
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function ChatHistoryImportSettings({
  task,
  depth,
  participantIds,
  extractMemories,
  updateProfiles,
  starting,
  deleting,
  onDepthChange,
  onParticipantsChange,
  onExtractMemoriesChange,
  onUpdateProfilesChange,
  onStart,
  onDelete,
}: ChatHistoryImportSettingsProps) {
  const analysis = task.analysis
  if (!analysis) return null

  return (
    <section aria-labelledby="settings-title">
      <p id="settings-title" className="ios-section-label mb-2">
        学习设置
      </p>
      <div className="space-y-4">
        <RadioGroup
          value={depth}
          onValueChange={(value) => onDepthChange(value as ChatHistoryLearningDepth)}
          className="grid gap-3 md:grid-cols-3"
        >
          {depthOptions.map((option) => (
            <label
              key={option.value}
              className={cn(
                'ios-group ios-touch flex cursor-pointer items-start gap-3 p-4',
                depth === option.value && 'border-primary/25 bg-primary/[0.055]'
              )}
            >
              <RadioGroupItem value={option.value} className="mt-0.5" />
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">{option.label}</span>
                  <span className="text-[13px] tabular-nums text-muted-foreground">
                    约 {task.estimated_model_calls[option.value] ?? 0} 次模型调用
                  </span>
                </span>
                <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">
                  {option.description}
                </span>
              </span>
            </label>
          ))}
        </RadioGroup>

        <div className="ios-group overflow-hidden">
          <div className="ios-row ios-row-plain">
            <span>
              <span className="block text-[16px] leading-6">参与学习的成员</span>
              <span className="block text-[13px] leading-5 text-muted-foreground">
                取消选择会排除该成员的表达、行为、黑话、记忆与画像候选
              </span>
            </span>
            <span className="ios-value">已选 {participantIds.size}</span>
          </div>
          <div className="grid min-w-0 gap-px bg-border/45 sm:grid-cols-2 lg:grid-cols-3">
            {analysis.participants.map((participant) => (
              <label
                key={participant.source_id}
                className="flex min-h-[62px] min-w-0 cursor-pointer items-center gap-2 bg-white/[0.92] px-3 py-2 dark:bg-white/[0.095]"
              >
                <Checkbox
                  checked={participantIds.has(participant.source_id)}
                  disabled={participant.is_bot}
                  onCheckedChange={(checked) => {
                    const next = new Set(participantIds)
                    if (checked === true) next.add(participant.source_id)
                    else next.delete(participant.source_id)
                    onParticipantsChange(next)
                  }}
                />
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-[15px] font-medium">
                      {participantName(participant)}
                    </span>
                    {participant.is_bot && <Badge variant="outline">本 Bot</Badge>}
                  </span>
                  <span className="block truncate text-[12px] leading-5 text-muted-foreground">
                    {formatNumber(participant.message_count)} 条 · {participant.source_id}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="ios-group overflow-hidden">
          <label htmlFor="extract-history-memories" className="ios-row ios-touch cursor-pointer">
            <span className="min-w-0 flex-1">
              <span className="block text-[16px] leading-6">提取聊天记忆</span>
              <span className="block text-[13px] leading-5 text-muted-foreground">
                仅写入当前群聊，并过滤敏感个人信息
              </span>
            </span>
            <Switch
              id="extract-history-memories"
              checked={extractMemories}
              onCheckedChange={onExtractMemoriesChange}
            />
          </label>
          <label htmlFor="update-history-profiles" className="ios-row ios-touch cursor-pointer">
            <span className="min-w-0 flex-1">
              <span className="block text-[16px] leading-6">更新成员画像</span>
              <span className="block text-[13px] leading-5 text-muted-foreground">
                作为未验证画像隔离保存，不覆盖运行时身份
              </span>
            </span>
            <Switch
              id="update-history-profiles"
              checked={updateProfiles}
              onCheckedChange={onUpdateProfilesChange}
            />
          </label>
        </div>

        <Alert>
          <ShieldCheck className="h-4 w-4" />
          <p className="mb-1 text-[15px] font-semibold leading-5 tracking-normal">
            写入前会再次核验证据
          </p>
          <AlertDescription>
            表达不能来自 Bot；行为需有可观察结果；黑话词面必须出现在至少两条非 Bot
            证据中。聊天里的提示词或命令只会作为文本分析。
          </AlertDescription>
        </Alert>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={onDelete} disabled={deleting}>
            <Trash2 className="mr-2 h-4 w-4" />
            删除任务
          </Button>
          <Button onClick={onStart} disabled={starting || participantIds.size === 0}>
            {starting ? (
              <LoaderCircle className="ios-spin-slow mr-2 h-4 w-4" />
            ) : (
              <Sparkles className="mr-2 h-4 w-4" />
            )}
            开始学习
          </Button>
        </div>
      </div>
    </section>
  )
}
