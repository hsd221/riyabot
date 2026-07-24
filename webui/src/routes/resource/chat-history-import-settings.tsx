import { Info, LoaderCircle, ShieldCheck, Sparkles, Trash2, TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type {
  ChatHistoryImportTask,
  ChatHistoryLearningDepth,
  ChatHistoryParticipantScope,
} from '@/types/chat-history-import'
import { ChatHistoryParticipantPicker } from './chat-history-participant-picker'

const depthOptions: Array<{
  value: ChatHistoryLearningDepth
  label: string
  coverage: string
  mechanism: string
  bestFor: string
}> = [
  {
    value: 'fast',
    label: '快速',
    coverage: '从全时间轴挑选最多 8 个高信息窗口。',
    mechanism: '按时间分布、消息信号和重点成员综合采样，每个窗口独立提取后统一合并。',
    bestFor: '首次试跑、验证模型配置和提示词质量。',
  },
  {
    value: 'balanced',
    label: '均衡',
    coverage: '从全时间轴挑选最多 20 个高信息窗口。',
    mechanism: '比快速档覆盖更多时间段和成员，仍只处理被选中的代表性窗口。',
    bestFor: '日常导入，兼顾覆盖率、调用次数与结果稳定性。',
  },
  {
    value: 'deep',
    label: '深入',
    coverage: '从全时间轴挑选最多 40 个高信息窗口。',
    mechanism: '扩大时间跨度和成员覆盖，适合表达变化较多或对话分散的群聊。',
    bestFor: '希望降低漏掉少见表达和群内黑话的概率。',
  },
  {
    value: 'full',
    label: '全量',
    coverage: '按时间顺序处理聊天记录中的每一个自然窗口。',
    mechanism: '不做窗口采样；所有候选按提示词预算分批，并通过多层聚合去重为稳定模式。',
    bestFor: '需要完整扫描整个聊天记录，且可以接受最高模型成本和耗时。',
  },
]

interface ChatHistoryImportSettingsProps {
  task: ChatHistoryImportTask
  depth: ChatHistoryLearningDepth
  participantScope: ChatHistoryParticipantScope
  extractMemories: boolean
  updateProfiles: boolean
  starting: boolean
  deleting: boolean
  onDepthChange: (depth: ChatHistoryLearningDepth) => void
  onParticipantScopeChange: (scope: ChatHistoryParticipantScope) => void
  onExtractMemoriesChange: (enabled: boolean) => void
  onUpdateProfilesChange: (enabled: boolean) => void
  onStart: () => void
  onDelete: () => void
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function ChatHistoryImportSettings({
  task,
  depth,
  participantScope,
  extractMemories,
  updateProfiles,
  starting,
  deleting,
  onDepthChange,
  onParticipantScopeChange,
  onExtractMemoriesChange,
  onUpdateProfilesChange,
  onStart,
  onDelete,
}: ChatHistoryImportSettingsProps) {
  const analysis = task.analysis
  if (!analysis) return null
  const activeDepth = depthOptions.find((option) => option.value === depth) ?? depthOptions[1]
  const estimatedCalls = task.estimated_model_calls[depth] ?? 0
  const participantCount = analysis.eligible_participant_count ?? analysis.participant_count
  const hasParticipants =
    participantScope.mode === 'all'
      ? participantScope.excluded_ids.length < participantCount
      : participantScope.included_ids.length > 0

  return (
    <section aria-labelledby="settings-title">
      <p id="settings-title" className="ios-section-label mb-2">
        学习设置
      </p>
      <div className="space-y-4">
        <div className="ios-group overflow-hidden">
          <div className="p-3 sm:p-4">
            <RadioGroup
              value={depth}
              onValueChange={(value) => onDepthChange(value as ChatHistoryLearningDepth)}
              className="grid grid-cols-2 gap-1 rounded-[10px] bg-muted/70 p-1 sm:grid-cols-4"
              aria-label="学习模式"
            >
              {depthOptions.map((option) => (
                <label
                  key={option.value}
                  className={cn(
                    'ios-touch relative flex min-h-11 cursor-pointer items-center justify-center rounded-[8px] px-3 text-[14px] font-medium focus-within:ring-2 focus-within:ring-ring/35',
                    depth === option.value && 'bg-background shadow-[0_1px_3px_rgba(0,0,0,0.12)]'
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
          <div className="ios-row ios-row-plain items-start bg-muted/20 py-4">
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="text-[16px] font-semibold">{activeDepth.label}模式</span>
                <span className="text-[13px] tabular-nums text-muted-foreground">
                  最低估算 {formatNumber(estimatedCalls)} 次模型调用
                </span>
              </span>
              <span className="mt-3 grid gap-2 text-[13px] leading-5 text-muted-foreground sm:grid-cols-[88px_1fr]">
                <span className="font-medium text-foreground">扫描范围</span>
                <span>{activeDepth.coverage}</span>
                <span className="font-medium text-foreground">工作原理</span>
                <span>{activeDepth.mechanism}</span>
                <span className="font-medium text-foreground">适合场景</span>
                <span>{activeDepth.bestFor}</span>
              </span>
              <span className="mt-3 flex items-start gap-2 text-[12px] leading-5 text-muted-foreground">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>
                  每个自然窗口最多 80 条、12,000 字符，相邻窗口保留 6
                  条上下文。尾部对话续接或候选较多触发分层合并时会追加调用，因此实际调用可能高于最低估算。
                </span>
              </span>
            </span>
          </div>
        </div>

        {depth === 'full' ? (
          <Alert className="border-orange-500/25 bg-orange-500/[0.06]">
            <TriangleAlert className="h-4 w-4 text-orange-600 dark:text-orange-400" />
            <p className="mb-1 text-[15px] font-semibold leading-5 tracking-normal">
              全量模式成本最高
            </p>
            <AlertDescription>
              它保证每个自然窗口都参与分析，但仍只保留有证据、可复用且跨窗口合并后成立的表达模式，不会为每条消息机械生成一条表达。
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="ios-group overflow-hidden">
          <ChatHistoryParticipantPicker
            importId={task.import_id}
            participantCount={participantCount}
            scope={participantScope}
            onChange={onParticipantScopeChange}
          />
        </div>

        <div className="ios-group overflow-hidden">
          <label htmlFor="extract-history-memories" className="ios-row ios-touch cursor-pointer">
            <span className="min-w-0 flex-1">
              <span className="block text-[16px] leading-6">提取聊天记忆</span>
              <span className="block text-[13px] leading-5 text-muted-foreground">
                写入记忆系统并标记来源为当前群聊；context_sensitive
                记忆只会在同一群聊流中被检索，同时过滤敏感个人信息。
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
                写入标准 QQ
                人物画像，不创建隔离副本；如目标画像已存在，任务会在任何结果写入前暂停，由你逐个选择保留现有或应用导入内容。
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
          <Button onClick={onStart} disabled={starting || !hasParticipants}>
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
