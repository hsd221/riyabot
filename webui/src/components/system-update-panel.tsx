import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Download,
  GitBranch,
  Loader2,
  RefreshCw,
  Server,
} from 'lucide-react'

import { RestartingOverlay } from '@/components/RestartingOverlay'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import {
  createUpdateTask,
  getUpdateResult,
  getUpdateStatus,
  updateUpdatePreferences,
  type InstallationMode,
  type UpdateChannel,
  type UpdateStatus,
} from '@/lib/update-api'
import { cn } from '@/lib/utils'

const CHANNELS: Array<{ value: UpdateChannel; label: string }> = [
  { value: 'stable', label: '正式版' },
  { value: 'dev', label: '开发版' },
]

const INSTALLATION_LABELS: Record<InstallationMode, string> = {
  source: 'Git 源码',
  docker: 'Docker',
  archive: '压缩包',
}

function shortRevision(revision: string | null): string {
  return revision ? revision.slice(0, 8) : '未知'
}

function statusLabel(status: UpdateStatus): string {
  if (!status.target) return '未找到可用版本'
  if (status.block_code === 'target_behind') return '当前版本高于频道目标'
  if (!status.update_available) return '已是最新版本'
  if (status.can_apply) return '发现可安装更新'
  return '发现新版本'
}

export function SystemUpdatePanel() {
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [selectedChannel, setSelectedChannel] = useState<UpdateChannel | null>(null)
  const [loading, setLoading] = useState(true)
  const [savingChannel, setSavingChannel] = useState(false)
  const [startingUpdate, setStartingUpdate] = useState(false)
  const [showUpdateOverlay, setShowUpdateOverlay] = useState(false)
  const requestedRevisionRef = useRef<string | null>(null)
  const { toast } = useToast()

  const loadStatus = useCallback(
    async (force: boolean) => {
      setLoading(true)
      try {
        const nextStatus = await getUpdateStatus(force)
        setStatus(nextStatus)
        setSelectedChannel(nextStatus.channel)
      } catch (error) {
        toast({
          title: '检查更新失败',
          description: error instanceof Error ? error.message : '无法连接更新服务',
          variant: 'destructive',
        })
      } finally {
        setLoading(false)
      }
    },
    [toast]
  )

  useEffect(() => {
    void loadStatus(false)
  }, [loadStatus])

  const changeChannel = async (channel: UpdateChannel) => {
    if (savingChannel || channel === selectedChannel) return
    setSavingChannel(true)
    try {
      await updateUpdatePreferences(channel)
      setSelectedChannel(channel)
      setStatus(null)
      await loadStatus(true)
      toast({
        title: '更新频道已切换',
        description: channel === 'stable' ? '当前跟踪正式版本' : '当前跟踪开发分支',
      })
    } catch (error) {
      toast({
        title: '切换失败',
        description: error instanceof Error ? error.message : '无法保存更新频道',
        variant: 'destructive',
      })
    } finally {
      setSavingChannel(false)
    }
  }

  const startUpdate = async () => {
    if (!status?.target || !status.can_apply || startingUpdate) return
    setStartingUpdate(true)
    try {
      await createUpdateTask(status.target.revision)
      requestedRevisionRef.current = status.target.revision
      setShowUpdateOverlay(true)
    } catch (error) {
      toast({
        title: '无法开始更新',
        description: error instanceof Error ? error.message : '更新任务创建失败',
        variant: 'destructive',
      })
      await loadStatus(true)
    } finally {
      setStartingUpdate(false)
    }
  }

  const verifyRestartComplete = useCallback(async () => {
    const result = await getUpdateResult()
    const requestedRevision = requestedRevisionRef.current
    return (
      requestedRevision !== null &&
      result.last_result?.success === true &&
      result.last_result.target_revision === requestedRevision
    )
  }, [])

  const channel = selectedChannel ?? status?.channel ?? 'stable'
  const targetLabel = status?.target
    ? status.channel === 'stable'
      ? status.target.ref
      : shortRevision(status.target.revision)
    : '不可用'

  return (
    <>
      <section className="ios-group overflow-hidden" aria-labelledby="system-update-heading">
        <div className="ios-row ios-row-plain items-start gap-3 py-4">
          <span className="ios-symbol ios-symbol-md ios-symbol-blue mt-0.5">
            <GitBranch className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2
                  id="system-update-heading"
                  className="text-[15px] font-semibold leading-5 text-foreground sm:text-base"
                >
                  程序更新
                </h2>
                <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                  {status
                    ? `${INSTALLATION_LABELS[status.current.installation_mode]} · RiyaBot ${status.current.version}`
                    : '正在读取版本信息'}
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-11 w-11 shrink-0"
                onClick={() => void loadStatus(true)}
                disabled={loading || savingChannel || startingUpdate}
                aria-label="重新检查更新"
                title="重新检查更新"
              >
                <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
              </Button>
            </div>

            <div
              className="mt-4 grid h-11 grid-cols-2 rounded-[8px] bg-muted/70 p-1"
              role="radiogroup"
              aria-label="更新频道"
            >
              {CHANNELS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  role="radio"
                  aria-checked={channel === item.value}
                  disabled={loading || savingChannel || startingUpdate}
                  onClick={() => void changeChannel(item.value)}
                  className={cn(
                    'min-w-0 rounded-[6px] px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    channel === item.value
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="border-t border-border/70 px-4 py-4 sm:px-5">
          {loading && !status ? (
            <div
              className="flex min-h-24 items-center justify-center text-muted-foreground"
              role="status"
            >
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在检查
            </div>
          ) : status ? (
            <div className="space-y-4">
              <div className="grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <p className="text-xs text-muted-foreground">当前提交</p>
                  <p className="mt-1 font-mono text-[13px] text-foreground">
                    {shortRevision(status.current.revision)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">频道目标</p>
                  <p className="mt-1 break-all font-mono text-[13px] text-foreground">
                    {targetLabel}
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 border-t border-border/70 pt-4">
                {status.update_available ? (
                  <Server className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                ) : (
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[rgb(52_199_89)]" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-foreground">{statusLabel(status)}</p>
                    {status.update_pending && <Badge variant="secondary">等待执行</Badge>}
                  </div>
                  {status.target?.summary && (
                    <p className="mt-1 line-clamp-2 break-words text-[13px] leading-5 text-muted-foreground">
                      {status.target.summary}
                    </p>
                  )}
                  {status.block_message && (
                    <p className="mt-2 flex items-start gap-2 text-[13px] leading-5 text-[rgb(176_98_0)] dark:text-[rgb(255_184_77)]">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{status.block_message}</span>
                    </p>
                  )}
                  {status.last_result && !status.last_result.success && (
                    <p className="text-destructive mt-2 text-[13px] leading-5">
                      上次更新：{status.last_result.message}
                    </p>
                  )}
                </div>
              </div>

              {status.update_available && status.can_apply && status.target && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      className="min-h-11 w-full"
                      disabled={startingUpdate || status.update_pending}
                    >
                      {startingUpdate ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Download className="mr-2 h-4 w-4" />
                      )}
                      {status.update_pending ? '等待 Runner 执行' : '立即更新'}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>更新到 {targetLabel}</AlertDialogTitle>
                      <AlertDialogDescription>
                        RiyaBot 将暂时离线。Runner 会验证目标提交、快进代码、同步依赖并重新构建
                        WebUI。
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction onClick={() => void startUpdate()}>
                        确认更新
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          ) : (
            <p className="min-h-24 py-8 text-center text-sm text-muted-foreground">
              暂时无法读取更新状态
            </p>
          )}
        </div>
      </section>

      {showUpdateOverlay && (
        <RestartingOverlay
          mode="update"
          verifyRestartComplete={verifyRestartComplete}
          onRestartComplete={() => window.location.reload()}
          onRestartFailed={() =>
            toast({
              title: '更新后服务未恢复',
              description: '请检查 Runner 日志中的更新结果',
              variant: 'destructive',
            })
          }
        />
      )}
    </>
  )
}
