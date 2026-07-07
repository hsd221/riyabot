import { useEffect, useState } from 'react'
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { Progress } from '@/components/ui/progress'
import { Button } from '@/components/ui/button'

interface RestartingOverlayProps {
  onRestartComplete?: () => void
  onRestartFailed?: () => void
}

export function RestartingOverlay({ onRestartComplete, onRestartFailed }: RestartingOverlayProps) {
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState<'restarting' | 'checking' | 'success' | 'failed'>(
    'restarting'
  )
  const [elapsedTime, setElapsedTime] = useState(0)
  const [checkAttempts, setCheckAttempts] = useState(0)

  useEffect(() => {
    // 进度条动画
    const progressInterval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 90) return prev
        return prev + 1
      })
    }, 200)

    // 计时器
    const timerInterval = setInterval(() => {
      setElapsedTime((prev) => prev + 1)
    }, 1000)

    // 等待3秒后开始检查状态（给后端重启时间）
    const initialDelay = setTimeout(() => {
      setStatus('checking')
      startHealthCheck()
    }, 3000)

    return () => {
      clearInterval(progressInterval)
      clearInterval(timerInterval)
      clearTimeout(initialDelay)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startHealthCheck = () => {
    const maxAttempts = 60 // 最多尝试60次（约2分钟）

    const checkHealth = async () => {
      try {
        setCheckAttempts((prev) => prev + 1)

        const response = await fetch('/api/webui/system/status', {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
          signal: AbortSignal.timeout(3000), // 3秒超时
        })

        if (response.ok) {
          // 重启成功
          setProgress(100)
          setStatus('success')
          setTimeout(() => {
            onRestartComplete?.()
          }, 1500)
        } else {
          throw new Error('Status check failed')
        }
      } catch {
        // 继续尝试
        if (checkAttempts < maxAttempts) {
          setTimeout(checkHealth, 2000) // 2秒后重试
        } else {
          // 超过最大尝试次数
          setStatus('failed')
          onRestartFailed?.()
        }
      }
    }

    checkHealth()
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const statusHint = {
    restarting: '配置已保存，正在重启主程序。',
    checking: '正在等待服务恢复，请勿关闭页面。',
    success: '配置已生效，服务运行正常。',
    failed: '如果长时间无响应，请尝试手动重启。',
  }[status]

  return (
    <div className="bg-background/82 fixed inset-0 z-50 flex items-center justify-center p-5 backdrop-blur-2xl">
      <div className="ios-card mx-auto w-full max-w-md space-y-7 p-6 sm:p-7">
        {/* 图标和状态 */}
        <div className="flex flex-col items-center space-y-4">
          {status === 'restarting' && (
            <>
              <span className="ios-symbol ios-symbol-blue flex h-16 w-16 rounded-[20px]">
                <Loader2 className="h-8 w-8 animate-spin" />
              </span>
              <h2 className="text-2xl font-semibold">正在重启主程序</h2>
              <p className="text-center text-muted-foreground">请稍候，主程序正在重启中。</p>
            </>
          )}

          {status === 'checking' && (
            <>
              <span className="ios-symbol ios-symbol-blue flex h-16 w-16 rounded-[20px]">
                <Loader2 className="h-8 w-8 animate-spin" />
              </span>
              <h2 className="text-2xl font-semibold">检查服务状态</h2>
              <p className="text-center text-muted-foreground">
                等待服务恢复... (尝试 {checkAttempts}/60)
              </p>
            </>
          )}

          {status === 'success' && (
            <>
              <span className="ios-symbol ios-symbol-green flex h-16 w-16 rounded-[20px]">
                <CheckCircle2 className="h-8 w-8" />
              </span>
              <h2 className="text-2xl font-semibold">重启成功</h2>
              <p className="text-center text-muted-foreground">正在跳转到登录页面。</p>
            </>
          )}

          {status === 'failed' && (
            <>
              <span className="ios-symbol ios-symbol-red flex h-16 w-16 rounded-[20px]">
                <AlertCircle className="h-8 w-8" />
              </span>
              <h2 className="text-2xl font-semibold">重启超时</h2>
              <p className="text-center text-muted-foreground">
                服务未能在预期时间内恢复，请手动检查或刷新页面
              </p>
            </>
          )}
        </div>

        {/* 进度条 */}
        {status !== 'failed' && (
          <div className="space-y-2">
            <Progress value={progress} className="h-2" />
            <div className="flex justify-between text-sm text-muted-foreground">
              <span>{progress}%</span>
              <span>已用时: {formatTime(elapsedTime)}</span>
            </div>
          </div>
        )}

        {/* 提示信息 */}
        <div className="ios-group px-4 py-3">
          <p className="text-sm leading-5 text-muted-foreground">{statusHint}</p>
        </div>

        {/* 失败时的操作按钮 */}
        {status === 'failed' && (
          <div className="flex gap-2">
            <Button onClick={() => window.location.reload()} className="flex-1">
              刷新页面
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setStatus('checking')
                setCheckAttempts(0)
                startHealthCheck()
              }}
              className="flex-1"
            >
              重试检测
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
