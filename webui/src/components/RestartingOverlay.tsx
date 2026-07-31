import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fetchWithAuth } from '@/lib/fetch-with-auth'
import { pollRestartHealth } from '@/lib/restart-health-polling'

interface RestartingOverlayProps {
  mode?: 'restart' | 'update'
  verifyRestartComplete?: () => Promise<boolean>
  onRestartComplete?: () => void
  onRestartFailed?: () => void
}

const INITIAL_DELAY_MS = 3000
const RETRY_DELAY_MS = 2000
const REQUEST_TIMEOUT_MS = 3000
const MAX_ATTEMPTS = 60
const UPDATE_MAX_ATTEMPTS = 180

export function RestartingOverlay({
  mode = 'restart',
  verifyRestartComplete,
  onRestartComplete,
  onRestartFailed,
}: RestartingOverlayProps) {
  const [status, setStatus] = useState<'restarting' | 'checking' | 'success' | 'failed'>(
    'restarting'
  )
  const [elapsedTime, setElapsedTime] = useState(0)
  const [checkAttempts, setCheckAttempts] = useState(0)
  const [failureKind, setFailureKind] = useState<'timeout' | 'verification' | null>(null)
  const runIdRef = useRef(0)
  const successTimerRef = useRef<number | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const verifyRestartCompleteRef = useRef(verifyRestartComplete)
  const onRestartCompleteRef = useRef(onRestartComplete)
  const onRestartFailedRef = useRef(onRestartFailed)
  const maxAttemptsRef = useRef(mode === 'update' ? UPDATE_MAX_ATTEMPTS : MAX_ATTEMPTS)
  verifyRestartCompleteRef.current = verifyRestartComplete
  onRestartCompleteRef.current = onRestartComplete
  onRestartFailedRef.current = onRestartFailed

  const cancelPolling = useCallback(() => {
    runIdRef.current += 1
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    if (successTimerRef.current !== null) window.clearTimeout(successTimerRef.current)
    successTimerRef.current = null
  }, [])

  const startHealthCheck = useCallback(() => {
    cancelPolling()
    const runId = runIdRef.current
    const controller = new AbortController()
    abortControllerRef.current = controller
    setStatus('checking')
    setFailureKind(null)
    setCheckAttempts(0)

    const checkHealth = async (signal: AbortSignal): Promise<boolean> => {
      const requestController = new AbortController()
      const handleAbort = () => requestController.abort()
      signal.addEventListener('abort', handleAbort, { once: true })
      const timeout = window.setTimeout(() => requestController.abort(), REQUEST_TIMEOUT_MS)

      try {
        const response = await fetchWithAuth('/api/webui/system/status', {
          method: 'GET',
          cache: 'no-store',
          signal: requestController.signal,
        })
        return response.ok
      } finally {
        window.clearTimeout(timeout)
        signal.removeEventListener('abort', handleAbort)
      }
    }

    void pollRestartHealth({
      check: checkHealth,
      signal: controller.signal,
      maxAttempts: maxAttemptsRef.current,
      retryDelayMs: RETRY_DELAY_MS,
      onAttempt: setCheckAttempts,
    }).then(async (result) => {
      if (runIdRef.current !== runId || result === 'cancelled') return
      if (abortControllerRef.current === controller) abortControllerRef.current = null

      if (result === 'success') {
        try {
          const verify = verifyRestartCompleteRef.current
          if (verify && !(await verify())) {
            if (runIdRef.current !== runId) return
            setFailureKind('verification')
            setStatus('failed')
            onRestartFailedRef.current?.()
            return
          }
        } catch {
          if (runIdRef.current !== runId) return
          setFailureKind('verification')
          setStatus('failed')
          onRestartFailedRef.current?.()
          return
        }
        if (runIdRef.current !== runId) return
        setStatus('success')
        successTimerRef.current = window.setTimeout(() => {
          if (runIdRef.current === runId) onRestartCompleteRef.current?.()
        }, 1200)
        return
      }

      setFailureKind('timeout')
      setStatus('failed')
      onRestartFailedRef.current?.()
    })
  }, [cancelPolling])

  useEffect(() => {
    const elapsedTimer = window.setInterval(() => setElapsedTime((previous) => previous + 1), 1000)
    const initialTimer = window.setTimeout(startHealthCheck, INITIAL_DELAY_MS)

    return () => {
      window.clearInterval(elapsedTimer)
      window.clearTimeout(initialTimer)
      cancelPolling()
    }
  }, [cancelPolling, startHealthCheck])

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
  }

  const statusHint = {
    restarting:
      mode === 'update'
        ? 'Runner 正在验证并安装所选版本。'
        : '配置已保存，正在等待主程序退出并重新启动。',
    checking: '正在探测服务是否恢复，请勿关闭页面。',
    success: mode === 'update' ? '新版本已启动，服务运行正常。' : '配置已生效，服务运行正常。',
    failed:
      mode === 'update' && failureKind === 'verification'
        ? '服务已经恢复，但 Runner 未确认本次更新成功。请检查更新结果与 Runner 日志。'
        : mode === 'update'
          ? '服务未在约六分钟内恢复，请检查 Runner 日志。'
          : '服务未在约两分钟内恢复，请检查控制台或手动重启。',
  }[status]
  const liveRole = status === 'failed' ? 'alert' : 'status'

  return (
    <div className="bg-background/82 fixed inset-0 z-50 flex items-center justify-center p-5 backdrop-blur-2xl">
      <div
        className="ios-card mx-auto w-full max-w-md space-y-7 p-6 sm:p-7"
        role={liveRole}
        aria-live="polite"
        aria-busy={status === 'restarting' || status === 'checking'}
      >
        <div className="flex flex-col items-center space-y-4">
          {(status === 'restarting' || status === 'checking') && (
            <span className="ios-symbol ios-symbol-blue flex h-16 w-16 rounded-[20px]">
              <Loader2 className="ios-spin-slow h-8 w-8" />
            </span>
          )}
          {status === 'success' && (
            <span className="ios-symbol ios-symbol-green flex h-16 w-16 rounded-[20px]">
              <CheckCircle2 className="h-8 w-8" />
            </span>
          )}
          {status === 'failed' && (
            <span className="ios-symbol ios-symbol-red flex h-16 w-16 rounded-[20px]">
              <AlertCircle className="h-8 w-8" />
            </span>
          )}

          <div className="text-center">
            <h2 className="text-2xl font-semibold">
              {status === 'restarting' && (mode === 'update' ? '正在安装更新' : '正在重启主程序')}
              {status === 'checking' && '检查服务状态'}
              {status === 'success' && (mode === 'update' ? '更新成功' : '重启成功')}
              {status === 'failed' &&
                (mode === 'update'
                  ? failureKind === 'verification'
                    ? '更新未完成'
                    : '更新超时'
                  : '重启超时')}
            </h2>
            <p className="mt-2 text-muted-foreground">
              {status === 'checking'
                ? `第 ${checkAttempts}/${maxAttemptsRef.current} 次检测 · 已用时 ${formatTime(elapsedTime)}`
                : statusHint}
            </p>
          </div>
        </div>

        {status === 'checking' && (
          <div className="relative h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
            <div className="motion-progress-indeterminate absolute inset-y-0 left-0 w-1/3 rounded-full bg-primary motion-reduce:left-1/2 motion-reduce:-translate-x-1/2" />
          </div>
        )}

        {status !== 'checking' && (
          <div className="ios-group px-4 py-3">
            <p className="text-sm leading-5 text-muted-foreground">{statusHint}</p>
          </div>
        )}

        {status === 'failed' && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button onClick={() => window.location.reload()} className="flex-1">
              刷新页面
            </Button>
            <Button variant="outline" onClick={startHealthCheck} className="flex-1">
              重试检测
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
