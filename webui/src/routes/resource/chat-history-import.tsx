import {
  Activity,
  BrainCircuit,
  Clock3,
  FileJson2,
  Filter,
  History,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UploadCloud,
  Users,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
import {
  deleteChatHistoryImport,
  getChatHistoryImport,
  listChatHistoryImports,
  startChatHistoryImport,
  uploadChatHistory,
} from '@/lib/chat-history-import-api'
import { chatHistoryProgressPercent } from '@/lib/chat-history-import-view'
import { cn } from '@/lib/utils'
import type {
  ChatHistoryImportStatus,
  ChatHistoryImportTask,
  ChatHistoryLearningDepth,
} from '@/types/chat-history-import'
import { ChatHistoryImportResult } from './chat-history-import-result'
import { ChatHistoryImportSettings } from './chat-history-import-settings'

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024

const statusLabels: Record<ChatHistoryImportStatus, string> = {
  analyzing: '分析中',
  ready: '待确认',
  running: '学习中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const stageLabels: Record<string, string> = {
  analyzing: '正在解析和降噪',
  ready: '等待确认学习设置',
  queued: '已进入学习队列',
  extracting: '正在分窗口联合提取',
  consolidating: '正在跨窗口合并候选',
  storing: '正在写入表达、行为与黑话库',
  storing_enrichment: '正在写入记忆与未验证画像',
  completed: '学习完成',
  failed: '学习失败',
  cancelled: '任务已取消',
}

const noiseLabels: Record<string, string> = {
  system: '系统消息',
  recalled: '撤回消息',
  no_text: '纯媒体 / 仅 @',
  punctuation_only: '纯标点',
  duplicate_burst: '同人短时刷屏',
  duplicate_id: '重复消息 ID',
  invalid_message: '损坏消息',
  invalid_timestamp: '无效时间戳',
  missing_sender: '缺少发送者',
  missing_message_id: '缺少消息 ID',
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}

function formatDate(timestamp: number | null): string {
  if (!timestamp) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(timestamp * 1000))
}

function StatusBadge({ status }: { status: ChatHistoryImportStatus }) {
  const destructive = status === 'failed' || status === 'cancelled'
  const complete = status === 'completed'
  return (
    <Badge variant={destructive ? 'destructive' : complete ? 'default' : 'secondary'}>
      {statusLabels[status]}
    </Badge>
  )
}

export function ChatHistoryImportPage() {
  const { toast } = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [tasks, setTasks] = useState<ChatHistoryImportTask[]>([])
  const [activeTask, setActiveTask] = useState<ChatHistoryImportTask | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [depth, setDepth] = useState<ChatHistoryLearningDepth>('balanced')
  const [participantIds, setParticipantIds] = useState<Set<string>>(new Set())
  const [extractMemories, setExtractMemories] = useState(false)
  const [updateProfiles, setUpdateProfiles] = useState(false)
  const activeTaskId = activeTask?.import_id
  const activeTaskStatus = activeTask?.status

  const loadTasks = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await listChatHistoryImports(signal)
        setTasks(response.data)
        setActiveTask((current) => {
          if (current) {
            return (
              response.data.find((task) => task.import_id === current.import_id) ??
              response.data[0] ??
              null
            )
          }
          return response.data[0] ?? null
        })
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return
        toast({
          title: '加载失败',
          description: error instanceof Error ? error.message : '无法获取导入任务',
          variant: 'destructive',
        })
      } finally {
        setLoading(false)
      }
    },
    [toast]
  )

  useEffect(() => {
    const controller = new AbortController()
    loadTasks(controller.signal)
    return () => controller.abort()
  }, [loadTasks])

  useEffect(() => {
    if (!activeTaskId || !activeTaskStatus || !['analyzing', 'running'].includes(activeTaskStatus))
      return
    const controller = new AbortController()
    const timer = window.setInterval(async () => {
      try {
        const updated = await getChatHistoryImport(activeTaskId, controller.signal)
        setActiveTask(updated)
        setTasks((current) =>
          current.map((task) => (task.import_id === updated.import_id ? updated : task))
        )
      } catch (error) {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          console.error('轮询聊天记录导入任务失败:', error)
        }
      }
    }, 1500)
    return () => {
      window.clearInterval(timer)
      controller.abort()
    }
  }, [activeTaskId, activeTaskStatus])

  useEffect(() => {
    if (!activeTask?.analysis) {
      setParticipantIds(new Set())
      setExtractMemories(false)
      setUpdateProfiles(false)
      return
    }
    const configured = activeTask.options.participant_ids
    const defaults = activeTask.analysis.participants
      .filter((participant) => !participant.is_bot)
      .map((participant) => participant.source_id)
    setParticipantIds(new Set(configured?.length ? configured : defaults))
    setDepth(activeTask.options.depth ?? 'balanced')
    setExtractMemories(activeTask.options.extract_memories ?? false)
    setUpdateProfiles(activeTask.options.update_profiles ?? false)
  }, [
    activeTask?.analysis,
    activeTask?.import_id,
    activeTask?.options.depth,
    activeTask?.options.extract_memories,
    activeTask?.options.participant_ids,
    activeTask?.options.update_profiles,
  ])

  const processFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith('.json')) {
        toast({
          title: '文件不受支持',
          description: '请选择 JSON 聊天记录文件',
          variant: 'destructive',
        })
        return
      }
      if (file.size <= 0 || file.size > MAX_UPLOAD_BYTES) {
        toast({
          title: '文件大小不符合要求',
          description: '聊天记录文件需大于 0 且不超过 100 MiB',
          variant: 'destructive',
        })
        return
      }
      try {
        setUploading(true)
        const task = await uploadChatHistory(file)
        setActiveTask(task)
        setTasks((current) => [
          task,
          ...current.filter((item) => item.import_id !== task.import_id),
        ])
        toast({
          title: '分析完成',
          description: `保留 ${formatNumber(task.analysis?.retained_messages ?? 0)} 条有效消息，请确认学习设置`,
        })
      } catch (error) {
        toast({
          title: '导入失败',
          description: error instanceof Error ? error.message : '无法分析聊天记录',
          variant: 'destructive',
        })
      } finally {
        setUploading(false)
        if (fileInputRef.current) fileInputRef.current.value = ''
      }
    },
    [toast]
  )

  const handleStart = async () => {
    if (!activeTask) return
    try {
      setStarting(true)
      const updated = await startChatHistoryImport(activeTask.import_id, {
        depth,
        participant_ids: Array.from(participantIds),
        extract_memories: extractMemories,
        update_profiles: updateProfiles,
      })
      setActiveTask(updated)
      setTasks((current) =>
        current.map((task) => (task.import_id === updated.import_id ? updated : task))
      )
      toast({ title: '学习已开始', description: '页面会持续更新提取、合并和写入进度' })
    } catch (error) {
      toast({
        title: '启动失败',
        description: error instanceof Error ? error.message : '无法启动聊天记录学习',
        variant: 'destructive',
      })
    } finally {
      setStarting(false)
    }
  }

  const handleDelete = async () => {
    if (!activeTask) return
    try {
      setDeleting(true)
      const response = await deleteChatHistoryImport(activeTask.import_id)
      toast({
        title: activeTask.status === 'running' ? '已请求取消' : '已删除',
        description: response.message,
      })
      await loadTasks()
    } catch (error) {
      toast({
        title: '操作失败',
        description: error instanceof Error ? error.message : '无法删除导入任务',
        variant: 'destructive',
      })
    } finally {
      setDeleting(false)
    }
  }

  const analysis = activeTask?.analysis
  const retainedRatio = analysis?.total_messages
    ? Math.round((analysis.retained_messages / analysis.total_messages) * 100)
    : 0
  const progressValue = activeTask
    ? chatHistoryProgressPercent(
        activeTask.status,
        activeTask.progress.stage,
        activeTask.progress.current,
        activeTask.progress.total
      )
    : 0

  return (
    <div className="ios-page flex h-[calc(100vh-4rem)] flex-col">
      <div className="mb-5 flex flex-col justify-between gap-4 sm:mb-6 sm:flex-row sm:items-center">
        <div>
          <h1 className="ios-title">聊天记录学习</h1>
          <p className="ios-subtitle">导入 QQ 群聊，集中学习表达方式、行为模式与群内黑话</p>
        </div>
        <Button
          variant="outline"
          className="hidden gap-2 sm:inline-flex"
          onClick={() => loadTasks()}
        >
          <RefreshCw className="h-4 w-4" />
          刷新任务
        </Button>
      </div>

      <ScrollArea className="min-h-0 min-w-0 flex-1">
        <div className="ios-content min-w-0 pb-6 sm:pr-4">
          <section aria-labelledby="upload-title">
            <p className="ios-section-label mb-2">导入</p>
            <div
              className={cn(
                'ios-group flex min-h-[188px] flex-col items-center justify-center gap-4 border-2 border-dashed px-6 py-8 text-center transition-colors',
                dragging
                  ? 'border-primary/50 bg-primary/[0.055]'
                  : 'border-black/[0.055] dark:border-white/15'
              )}
              onDragEnter={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                event.preventDefault()
                if (event.currentTarget === event.target) setDragging(false)
              }}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                const file = event.dataTransfer.files[0]
                if (file) processFile(file)
              }}
            >
              <span className="ios-symbol ios-symbol-purple h-14 w-14 rounded-[16px]">
                {uploading ? (
                  <LoaderCircle className="ios-spin-slow h-7 w-7" />
                ) : (
                  <UploadCloud className="h-7 w-7" />
                )}
              </span>
              <div>
                <h2 id="upload-title" className="text-[18px] font-semibold leading-7">
                  {uploading ? '正在上传并分析' : '拖入 QQChatExporter JSON'}
                </h2>
                <p className="mt-1 text-[14px] leading-6 text-muted-foreground">
                  最大 100 MiB；原始文件分析后立即删除，只暂存降噪后的文本
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                aria-label="选择 QQChatExporter JSON 聊天记录"
                className="sr-only"
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) processFile(file)
                }}
              />
              <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                <FileJson2 className="mr-2 h-4 w-4" />
                选择聊天记录
              </Button>
            </div>
          </section>

          {tasks.length > 0 && (
            <section aria-labelledby="tasks-title">
              <div className="mb-2 flex items-center justify-between gap-3 px-1">
                <p id="tasks-title" className="ios-section-label px-0">
                  最近任务
                </p>
                <span className="text-[13px] text-muted-foreground">
                  显示最近 {Math.min(tasks.length, 8)} 条
                </span>
              </div>
              <div className="ios-group overflow-hidden">
                {tasks.slice(0, 8).map((task) => (
                  <button
                    type="button"
                    key={task.import_id}
                    onClick={() => setActiveTask(task)}
                    className={cn(
                      'ios-row ios-touch w-full text-left focus-visible:ring-0',
                      activeTask?.import_id === task.import_id && 'bg-primary/[0.055]'
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                        <History className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-[16px] font-medium leading-6">
                          {task.analysis?.chat.name ?? task.source_name}
                        </span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          {formatBytes(task.source_size)} · {formatDate(task.created_at)}
                        </span>
                      </span>
                    </span>
                    <StatusBadge status={task.status} />
                  </button>
                ))}
              </div>
            </section>
          )}

          {loading && tasks.length === 0 && (
            <div className="ios-status-panel mx-auto">
              <span className="ios-symbol ios-symbol-md ios-symbol-blue">
                <LoaderCircle className="ios-spin-slow h-5 w-5" />
              </span>
              <p className="text-[15px] text-muted-foreground">正在加载导入任务...</p>
            </div>
          )}

          {activeTask && analysis && (
            <>
              <section aria-labelledby="analysis-title">
                <div className="mb-2 flex items-center justify-between gap-3 px-1">
                  <p id="analysis-title" className="ios-section-label px-0">
                    分析结果
                  </p>
                  <StatusBadge status={activeTask.status} />
                </div>
                <div className="ios-group overflow-hidden">
                  <div className="grid grid-cols-2 gap-px bg-border/45 lg:grid-cols-4">
                    {[
                      {
                        label: '原始消息',
                        value: formatNumber(analysis.total_messages),
                        icon: MessageSquareText,
                      },
                      {
                        label: '有效消息',
                        value: formatNumber(analysis.retained_messages),
                        icon: ShieldCheck,
                      },
                      {
                        label: '自然窗口',
                        value: formatNumber(analysis.total_window_count),
                        icon: Activity,
                      },
                      {
                        label: '参与者',
                        value: formatNumber(analysis.participants.length),
                        icon: Users,
                      },
                    ].map(({ label, value, icon: Icon }) => (
                      <div key={label} className="bg-white/[0.92] p-4 dark:bg-white/[0.095] sm:p-5">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-[13px] font-medium text-muted-foreground">
                            {label}
                          </span>
                          <Icon className="h-4 w-4 text-primary" />
                        </div>
                        <p className="mt-3 text-[25px] font-semibold tabular-nums leading-none">
                          {value}
                        </p>
                      </div>
                    ))}
                  </div>
                  <div className="ios-row ios-row-plain">
                    <span className="min-w-0">
                      <span className="block text-[16px] leading-6">{analysis.chat.name}</span>
                      <span className="block text-[13px] leading-5 text-muted-foreground">
                        群号 {analysis.chat.source_id} · {formatDate(analysis.start_timestamp)} 至{' '}
                        {formatDate(analysis.end_timestamp)}
                      </span>
                    </span>
                    <span className="ios-value">保留 {retainedRatio}%</span>
                  </div>
                </div>
              </section>

              <section aria-labelledby="noise-title">
                <p id="noise-title" className="ios-section-label mb-2">
                  噪声过滤
                </p>
                <div className="ios-group overflow-hidden">
                  <div className="ios-row ios-row-plain">
                    <span className="flex items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                        <Filter className="h-4 w-4" />
                      </span>
                      <span>
                        <span className="block text-[16px] leading-6">已过滤噪声</span>
                        <span className="block text-[13px] leading-5 text-muted-foreground">
                          短确认保留为上下文，但不会单独支撑表达或黑话
                        </span>
                      </span>
                    </span>
                    <span className="ios-value">{formatNumber(analysis.filtered_messages)} 条</span>
                  </div>
                  {Object.entries(analysis.noise_counts)
                    .sort(([, left], [, right]) => right - left)
                    .map(([key, count]) => (
                      <div key={key} className="ios-row ios-row-plain">
                        <span className="text-[15px] leading-6">{noiseLabels[key] ?? key}</span>
                        <span className="ios-value">{formatNumber(count)}</span>
                      </div>
                    ))}
                </div>
              </section>

              {activeTask.status === 'ready' && (
                <ChatHistoryImportSettings
                  task={activeTask}
                  depth={depth}
                  participantIds={participantIds}
                  extractMemories={extractMemories}
                  updateProfiles={updateProfiles}
                  starting={starting}
                  deleting={deleting}
                  onDepthChange={setDepth}
                  onParticipantsChange={setParticipantIds}
                  onExtractMemoriesChange={setExtractMemories}
                  onUpdateProfilesChange={setUpdateProfiles}
                  onStart={handleStart}
                  onDelete={handleDelete}
                />
              )}

              {activeTask.status === 'running' && (
                <section aria-labelledby="progress-title">
                  <p id="progress-title" className="ios-section-label mb-2">
                    学习进度
                  </p>
                  <div className="ios-group p-5 sm:p-6">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="ios-symbol ios-symbol-md ios-symbol-purple">
                          <BrainCircuit className="h-5 w-5" />
                        </span>
                        <div className="min-w-0">
                          <p className="font-medium">
                            {stageLabels[activeTask.progress.stage] ?? '正在学习'}
                          </p>
                          <p className="mt-0.5 truncate text-[13px] text-muted-foreground">
                            {activeTask.progress.current} / {activeTask.progress.total}
                          </p>
                        </div>
                      </div>
                      <span className="text-[18px] font-semibold tabular-nums">
                        {progressValue}%
                      </span>
                    </div>
                    <Progress value={progressValue} className="mt-5 h-2.5" />
                    <div className="mt-5 flex justify-end">
                      <Button variant="outline" onClick={handleDelete} disabled={deleting}>
                        <XCircle className="mr-2 h-4 w-4" />
                        取消任务
                      </Button>
                    </div>
                  </div>
                </section>
              )}

              {activeTask.status === 'completed' && activeTask.result && (
                <ChatHistoryImportResult
                  task={activeTask}
                  deleting={deleting}
                  onDelete={handleDelete}
                />
              )}

              {(activeTask.status === 'failed' || activeTask.status === 'cancelled') && (
                <div className="space-y-3">
                  <Alert variant="destructive">
                    <XCircle className="h-4 w-4" />
                    <p className="mb-1 text-[15px] font-semibold leading-5 tracking-normal">
                      {activeTask.status === 'failed' ? '任务失败' : '任务已取消'}
                    </p>
                    <AlertDescription>
                      {activeTask.error_message ?? '该任务没有产生学习结果。'}
                    </AlertDescription>
                  </Alert>
                  <div className="flex justify-end">
                    <Button variant="outline" onClick={handleDelete} disabled={deleting}>
                      <Trash2 className="mr-2 h-4 w-4" />
                      删除任务记录
                    </Button>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 text-[12px] leading-5 text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Clock3 className="h-3.5 w-3.5" /> 创建 {formatDate(activeTask.created_at)}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <FileJson2 className="h-3.5 w-3.5" /> {activeTask.source_name} ·{' '}
                  {formatBytes(activeTask.source_size)}
                </span>
              </div>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
