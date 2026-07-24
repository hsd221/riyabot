import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  CornerDownRight,
  Hash,
  Layers3,
  MessageSquareText,
  Trash2,
  Users,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { countHistoryCandidates } from '@/lib/chat-history-import-view'
import type { ChatHistoryImportTask } from '@/types/chat-history-import'

interface ChatHistoryImportResultProps {
  task: ChatHistoryImportTask
  deleting: boolean
  onDelete: () => void
}

export function ChatHistoryImportResult({
  task,
  deleting,
  onDelete,
}: ChatHistoryImportResultProps) {
  const result = task.result
  if (!result) return null

  const counts = countHistoryCandidates(result)
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0)

  return (
    <section aria-labelledby="result-title">
      <div className="mb-2 flex items-center justify-between gap-3 px-1">
        <p id="result-title" className="ios-section-label px-0">
          学习结果
        </p>
        <span className="text-[13px] text-muted-foreground">扫描与写入已完成</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[
          {
            label: '表达方式',
            value: counts.expressions,
            icon: MessageSquareText,
            color: 'ios-symbol-orange',
          },
          {
            label: '行为模式',
            value: counts.behaviors,
            icon: Activity,
            color: 'ios-symbol-purple',
          },
          { label: '群内黑话', value: counts.jargons, icon: Hash, color: 'ios-symbol-pink' },
          {
            label: '聊天记忆',
            value: counts.memories,
            icon: BrainCircuit,
            color: 'ios-symbol-blue',
          },
          { label: '成员画像', value: counts.profiles, icon: Users, color: 'ios-symbol-teal' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="ios-stat-card">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
              <span className={`ios-symbol ios-symbol-sm ${color}`}>
                <Icon className="h-4 w-4" />
              </span>
            </div>
            <p className="mt-5 text-[28px] font-semibold tabular-nums leading-none">{value}</p>
          </div>
        ))}
      </div>
      <div className="ios-group mt-4 overflow-hidden">
        <div className="ios-row ios-row-plain">
          <span className="flex items-center gap-3 text-[15px]">
            <Layers3 className="h-4 w-4 text-primary" aria-hidden="true" />
            基础窗口
          </span>
          <span className="ios-value">
            {result.selected_window_count ?? 0} / {result.total_window_count ?? 0}
          </span>
        </div>
        <div className="ios-row ios-row-plain">
          <span className="flex items-center gap-3 text-[15px]">
            <CornerDownRight className="h-4 w-4 text-primary" aria-hidden="true" />
            边界续接窗口
          </span>
          <span className="ios-value">{result.continuation_window_ids?.length ?? 0}</span>
        </div>
        <div className="ios-row ios-row-plain">
          <span className="flex items-center gap-3 text-[15px]">
            <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
            实际模型调用
          </span>
          <span className="ios-value">{result.model_call_count ?? 0}</span>
        </div>
      </div>
      {result.enrichment_store_result && (
        <div className="ios-group mt-4 overflow-hidden">
          <div className="ios-row ios-row-plain">
            <span className="text-[15px]">记忆写入</span>
            <span className="ios-value">{result.enrichment_store_result.memories_created} 条</span>
          </div>
          <div className="ios-row ios-row-plain">
            <span className="text-[15px]">画像写入</span>
            <span className="ios-value">
              {result.enrichment_store_result.profiles_created} 新建 ·{' '}
              {result.enrichment_store_result.profiles_updated} 更新
            </span>
          </div>
          {(result.enrichment_store_result.profiles_skipped > 0 ||
            result.enrichment_store_result.write_failures > 0) && (
            <div className="ios-row ios-row-plain">
              <span className="text-[15px]">受保护或未写入</span>
              <span className="ios-value">
                {result.enrichment_store_result.profiles_skipped} 跳过 ·{' '}
                {result.enrichment_store_result.write_failures} 失败
              </span>
            </div>
          )}
        </div>
      )}
      <div className="ios-group mt-4 overflow-hidden">
        {result.candidates.expressions.slice(0, 4).map((candidate, index) => (
          <div key={`expression-${index}`} className="ios-row ios-row-plain items-start">
            <span className="min-w-0">
              <span className="block font-medium">{candidate.situation}</span>
              <span className="mt-0.5 block text-[13px] leading-5 text-muted-foreground">
                {candidate.style}
              </span>
            </span>
            <Badge variant="outline">表达</Badge>
          </div>
        ))}
        {result.candidates.behaviors.slice(0, 4).map((candidate, index) => (
          <div key={`behavior-${index}`} className="ios-row ios-row-plain items-start">
            <span className="min-w-0">
              <span className="block font-medium">{candidate.action}</span>
              <span className="mt-0.5 block text-[13px] leading-5 text-muted-foreground">
                {candidate.outcome}
              </span>
            </span>
            <Badge variant="outline">行为</Badge>
          </div>
        ))}
        {result.candidates.jargons.slice(0, 6).map((candidate, index) => (
          <div key={`jargon-${index}`} className="ios-row ios-row-plain items-start">
            <span className="min-w-0">
              <span className="block font-medium">{candidate.content}</span>
              <span className="mt-0.5 block text-[13px] leading-5 text-muted-foreground">
                {candidate.meaning}
              </span>
            </span>
            <Badge variant="outline">黑话</Badge>
          </div>
        ))}
        {result.candidates.memories?.slice(0, 4).map((candidate, index) => (
          <div key={`memory-${index}`} className="ios-row ios-row-plain items-start">
            <span className="min-w-0 break-words font-medium">{candidate.content}</span>
            <Badge variant="outline">记忆</Badge>
          </div>
        ))}
        {result.candidates.profiles?.slice(0, 6).map((candidate, index) => (
          <div key={`profile-${index}`} className="ios-row ios-row-plain items-start">
            <span className="min-w-0 break-words">
              <span className="block font-medium">{candidate.name}</span>
              <span className="mt-0.5 block text-[13px] leading-5 text-muted-foreground">
                {candidate.value} · {candidate.subject_id}
              </span>
            </span>
            <Badge variant="outline">画像</Badge>
          </div>
        ))}
        {total === 0 && (
          <div className="ios-empty-state">
            <CheckCircle2 className="h-10 w-10 text-muted-foreground/50" />
            <p>本次没有足够可靠、可写入的学习候选</p>
          </div>
        )}
      </div>
      <div className="mt-4 flex justify-end">
        <Button variant="outline" onClick={onDelete} disabled={deleting}>
          <Trash2 className="mr-2 h-4 w-4" />
          删除审计记录
        </Button>
      </div>
    </section>
  )
}
