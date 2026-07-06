import { useEffect, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  AlertCircle,
  ChevronRight,
  FileText,
  HelpCircle,
  Key,
  Lock,
  Moon,
  Sun,
  Terminal,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { useTheme } from '@/components/use-theme'
import { checkAuthStatus } from '@/lib/fetch-with-auth'
import { checkFirstSetup } from '@/hooks/use-auth'
import { cn } from '@/lib/utils'
import { APP_FULL_NAME, APP_NAME } from '@/lib/version'

export function AuthPage() {
  const [token, setToken] = useState('')
  const [isValidating, setIsValidating] = useState(false)
  const [error, setError] = useState('')
  const [checkingAuth, setCheckingAuth] = useState(true)
  const navigate = useNavigate()
  const { theme, setTheme } = useTheme()

  // 如果已经认证，直接跳转到首页
  useEffect(() => {
    const verifyAuth = async () => {
      try {
        const isAuth = await checkAuthStatus()
        if (isAuth) {
          const needsSetup = await checkFirstSetup()
          navigate({ to: needsSetup ? '/setup' : '/' })
        }
      } catch {
        // 忽略错误，保持在登录页
      } finally {
        setCheckingAuth(false)
      }
    }
    verifyAuth()
  }, [navigate])

  // 获取实际应用的主题（处理 system 情况）
  const getActualTheme = () => {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    return theme
  }

  const actualTheme = getActualTheme()

  // 主题切换（无动画）
  const toggleTheme = () => {
    const newTheme = actualTheme === 'dark' ? 'light' : 'dark'
    setTheme(newTheme)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!token.trim()) {
      setError('请输入 Access Token')
      return
    }

    setIsValidating(true)

    try {
      // 向后端发送请求验证 token（后端会设置 HttpOnly Cookie）
      const response = await fetch('/api/webui/auth/verify', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include', // 确保接收并存储 Cookie
        body: JSON.stringify({ token: token.trim() }),
      })

      const data = await response.json()

      if (response.ok && data.valid) {
        // Token 验证成功，Cookie 已由后端设置
        // 直接使用验证响应中的 is_first_setup 字段，避免额外请求
        if (data.is_first_setup) {
          // 需要首次配置，跳转到配置向导
          navigate({ to: '/setup' })
        } else {
          // 不需要配置或配置已完成，跳转到首页
          navigate({ to: '/' })
        }
      } else {
        setError(data.message || 'Token 验证失败，请检查后重试')
      }
    } catch (err) {
      console.error('Token 验证错误:', err)
      setError('连接服务器失败，请检查网络连接')
    } finally {
      setIsValidating(false)
    }
  }

  // 正在检查认证状态时显示加载
  if (checkingAuth) {
    return (
      <div className="ios-page flex min-h-screen items-center justify-center overflow-hidden">
        <div className="ios-group px-5 py-3 text-sm leading-relaxed text-muted-foreground">
          正在检查登录状态...
        </div>
      </div>
    )
  }

  return (
    <div className="ios-page flex min-h-screen flex-col overflow-x-hidden">
      <button
        onClick={toggleTheme}
        className="ios-touch absolute right-[max(1rem,env(safe-area-inset-right))] top-[max(1rem,env(safe-area-inset-top))] z-10 grid h-11 w-11 place-items-center rounded-full text-foreground hover:bg-muted/70"
        title={actualTheme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
      >
        {actualTheme === 'dark' ? (
          <Sun className="h-5 w-5" strokeWidth={2.5} fill="none" />
        ) : (
          <Moon className="h-5 w-5" strokeWidth={2.5} fill="none" />
        )}
      </button>

      <main className="mx-auto flex w-full max-w-[27.5rem] flex-1 flex-col justify-center gap-7 py-10">
        <header className="space-y-4 text-left sm:text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-[18px] bg-primary text-primary-foreground shadow-[0_10px_24px_hsl(var(--primary)_/_0.22)] sm:mx-auto">
            <Lock className="h-7 w-7" strokeWidth={2.2} fill="none" />
          </div>

          <div className="space-y-3">
            <h1 className="text-[32px] font-semibold leading-[1.14] tracking-normal text-foreground">
              {APP_NAME}
            </h1>
            <p className="max-w-sm text-[17px] leading-[1.45] text-muted-foreground sm:mx-auto">
              输入 Access Token 继续访问控制台。
            </p>
          </div>
        </header>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="ios-group overflow-hidden">
            <label htmlFor="token" className="ios-row min-h-[64px] gap-3 px-4 py-2">
              <Key
                className="h-5 w-5 flex-shrink-0 text-muted-foreground"
                strokeWidth={2}
                fill="none"
              />
              <span className="shrink-0 text-[17px] font-medium leading-snug text-foreground">
                Access Token
              </span>
              <Input
                id="token"
                type="password"
                placeholder="请输入 Token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                className={cn(
                  'h-10 min-w-0 flex-1 border-0 bg-transparent px-0 text-right text-[17px] shadow-none placeholder:text-muted-foreground/70 focus-visible:ring-0 focus-visible:ring-offset-0',
                  error &&
                    'text-[rgb(174_37_31)] placeholder:text-[rgb(215_0_21_/_0.62)] dark:text-[rgb(255_105_97)]'
                )}
                disabled={isValidating}
                autoComplete="off"
              />
            </label>

            {error && (
              <div className="ios-row flex items-start gap-3 bg-[rgb(255_59_48_/_0.06)] px-4 py-3 text-sm leading-relaxed text-[rgb(174_37_31)] dark:text-[rgb(255_105_97)]">
                <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" strokeWidth={2} fill="none" />
                <span className="min-w-0">{error}</span>
              </div>
            )}
          </div>

          <Button
            type="submit"
            className="h-12 w-full rounded-full text-[17px] font-semibold shadow-[0_10px_24px_hsl(var(--primary)_/_0.2)] active:scale-[0.98]"
            disabled={isValidating}
          >
            {isValidating ? (
              <>
                <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                验证中...
              </>
            ) : (
              '验证并进入'
            )}
          </Button>

          <Dialog>
            <DialogTrigger asChild>
              <button
                type="button"
                className="ios-group ios-touch flex min-h-[54px] w-full items-center justify-between gap-3 px-4 py-3 text-left text-[15px] font-medium text-primary"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <HelpCircle className="h-5 w-5 flex-shrink-0" strokeWidth={2.2} fill="none" />
                  <span className="min-w-0 leading-snug">如何获取 Access Token</span>
                </span>
                <ChevronRight
                  className="h-5 w-5 flex-shrink-0 text-primary/70"
                  strokeWidth={2.2}
                  fill="none"
                />
              </button>
            </DialogTrigger>
            <DialogContent className="bottom-0 left-0 top-auto flex max-h-[86vh] w-full max-w-none translate-x-0 translate-y-0 flex-col overflow-hidden rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1rem,env(safe-area-inset-bottom))] sm:bottom-auto sm:left-[50%] sm:top-[50%] sm:max-h-[80vh] sm:max-w-md sm:translate-x-[-50%] sm:translate-y-[-50%] sm:rounded-[22px] sm:border sm:p-5 [&>button:last-child]:right-4 [&>button:last-child]:top-4">
              <DialogHeader className="px-5 pb-1 pt-5 sm:px-0 sm:pt-0">
                <DialogTitle className="flex items-center gap-2">
                  <Lock className="h-5 w-5 text-primary" strokeWidth={2} fill="none" />
                  如何获取 Access Token
                </DialogTitle>
                <DialogDescription>
                  Access Token 是访问 {APP_NAME} 的唯一凭证，请按以下方式获取
                </DialogDescription>
              </DialogHeader>

              <div className="ios-scrollbar-none max-h-[calc(86vh-8rem)] space-y-4 overflow-y-auto px-5 pb-5 sm:max-h-[60vh] sm:px-0 sm:pb-0">
                <div className="overflow-hidden rounded-[18px] border border-border/60 bg-card/80">
                  <div className="flex items-start gap-3 border-b border-border/60 px-4 py-4">
                    <Terminal
                      className="mt-0.5 h-5 w-5 flex-shrink-0 text-primary"
                      strokeWidth={2}
                      fill="none"
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                      <h4 className="text-sm font-semibold leading-snug">查看启动日志</h4>
                      <p className="text-sm leading-relaxed text-muted-foreground">
                        主程序启动时，控制台会显示 WebUI Access Token。
                      </p>
                      <div className="rounded-[12px] bg-muted/70 p-2.5 font-mono text-xs leading-relaxed">
                        <p className="text-muted-foreground">WebUI Access Token: abc123...</p>
                        <p className="text-muted-foreground">请使用此 Token 登录 WebUI</p>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-start gap-3 px-4 py-4">
                    <FileText
                      className="mt-0.5 h-5 w-5 flex-shrink-0 text-primary"
                      strokeWidth={2}
                      fill="none"
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                      <h4 className="text-sm font-semibold leading-snug">查看配置文件</h4>
                      <p className="text-sm leading-relaxed text-muted-foreground">
                        Token 保存在项目根目录的配置文件中：
                      </p>
                      <div className="break-all rounded-[12px] bg-muted/70 p-2.5 font-mono text-xs leading-relaxed">
                        <code className="text-primary">data/webui.json</code>
                      </div>
                      <p className="text-xs leading-relaxed text-muted-foreground">
                        打开此文件，复制{' '}
                        <code className="rounded bg-muted px-1 py-0.5">access_token</code> 字段的值
                      </p>
                    </div>
                  </div>
                </div>

                <div className="overflow-hidden rounded-[18px] border border-border/60 bg-card/80">
                  <div className="flex items-start gap-3 px-4 py-3">
                    <AlertCircle
                      className="mt-0.5 h-4 w-4 flex-shrink-0 text-[rgb(178_93_0)] dark:text-[rgb(255_159_10)]"
                      strokeWidth={2}
                      fill="none"
                    />
                    <div className="space-y-1 text-sm leading-relaxed text-muted-foreground">
                      <p className="font-semibold text-foreground">安全提示</p>
                      <p>请妥善保管您的 Token。需要重置时，可在登录后前往系统设置。</p>
                    </div>
                  </div>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </form>
      </main>

      <p className="pb-[max(0.25rem,env(safe-area-inset-bottom))] text-center text-[11px] leading-relaxed text-muted-foreground">
        {APP_FULL_NAME}
      </p>
    </div>
  )
}
