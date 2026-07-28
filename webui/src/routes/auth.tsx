import { useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  AlertCircle,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  Lock,
  Monitor,
  Moon,
  Sun,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { toggleThemeWithTransition, useTheme } from '@/components/use-theme'
import { getAuthStatus } from '@/lib/fetch-with-auth'
import { checkFirstSetup } from '@/hooks/use-auth'
import { cn } from '@/lib/utils'
import { APP_FULL_NAME, APP_NAME } from '@/lib/version'
import type { ComponentType, FormEvent } from 'react'
import type { LucideProps } from 'lucide-react'

type ThemeMode = 'light' | 'dark' | 'system'

const authThemeOptions: Array<{
  value: ThemeMode
  label: string
  description: string
  icon: ComponentType<LucideProps>
  symbolClass: string
}> = [
  {
    value: 'system',
    label: '跟随系统',
    description: '根据设备外观自动切换',
    icon: Monitor,
    symbolClass: 'ios-symbol-blue',
  },
  {
    value: 'light',
    label: '浅色模式',
    description: '始终使用浅色外观',
    icon: Sun,
    symbolClass: 'ios-symbol-yellow',
  },
  {
    value: 'dark',
    label: '深色模式',
    description: '始终使用深色外观',
    icon: Moon,
    symbolClass: 'ios-symbol-purple',
  },
]

export function AuthPage() {
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [error, setError] = useState('')
  const [checkingAuth, setCheckingAuth] = useState(true)
  const passwordInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { theme, resolvedTheme, setTheme } = useTheme()

  useEffect(() => {
    let cancelled = false

    const verifyAuth = async () => {
      try {
        const status = await getAuthStatus()
        if (cancelled) return

        if (!status.passwordConfigured) {
          navigate({ to: '/setup' })
          return
        }

        if (status.authenticated) {
          const needsSetup = await checkFirstSetup()
          if (!cancelled) {
            navigate({ to: needsSetup ? '/setup' : '/' })
          }
        }
      } finally {
        if (!cancelled) setCheckingAuth(false)
      }
    }

    verifyAuth()
    return () => {
      cancelled = true
    }
  }, [navigate])

  const CurrentThemeIcon = theme === 'system' ? Monitor : resolvedTheme === 'dark' ? Moon : Sun
  const themeLabel =
    theme === 'system' ? '跟随系统' : resolvedTheme === 'dark' ? '深色模式' : '浅色模式'

  const reportError = (message: string) => {
    setError(message)
    window.requestAnimationFrame(() => passwordInputRef.current?.focus())
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')

    if (!password) {
      reportError('请输入 WebUI 密码')
      return
    }

    setIsValidating(true)
    try {
      const response = await fetch('/api/webui/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        cache: 'no-store',
        body: JSON.stringify({ password }),
      })
      const data = await response.json().catch(() => null)

      if (response.ok && data?.valid) {
        navigate({ to: data.is_first_setup ? '/setup' : '/' })
        return
      }

      reportError(data?.detail || data?.message || '密码验证失败，请检查后重试')
    } catch (requestError) {
      console.error('WebUI 登录失败:', requestError)
      reportError('连接服务器失败，请检查网络连接')
    } finally {
      setIsValidating(false)
    }
  }

  if (checkingAuth) {
    return (
      <div className="ios-page ios-app-min-height flex items-center justify-center overflow-hidden">
        <div className="ios-status-panel" role="status" aria-live="polite">
          <span className="ios-symbol ios-symbol-md ios-symbol-blue">
            <LoaderCircle className="ios-spin-slow h-5 w-5" strokeWidth={2.5} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[16px] font-semibold leading-6 text-foreground">
              {APP_NAME}
            </p>
            <p className="text-[14px] leading-5 text-muted-foreground">正在检查登录状态...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="ios-page ios-app-min-height flex flex-col overflow-x-hidden">
      <Popover>
        <PopoverTrigger asChild>
          <button
            className="ios-touch absolute right-[max(1rem,env(safe-area-inset-right))] top-[max(1rem,env(safe-area-inset-top))] z-10 grid h-11 w-11 place-items-center rounded-full text-foreground hover:bg-muted/70"
            title={`外观：${themeLabel}`}
            aria-label={`外观：${themeLabel}`}
          >
            <CurrentThemeIcon className="h-5 w-5" strokeWidth={2.5} fill="none" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-60 p-1.5">
          <div className="overflow-hidden rounded-[14px]">
            {authThemeOptions.map((option) => {
              const OptionIcon = option.icon
              const selected = theme === option.value

              return (
                <button
                  key={option.value}
                  type="button"
                  className="ios-touch flex min-h-[54px] w-full items-center gap-3 border-b border-border/45 px-3 py-2.5 text-left last:border-b-0 hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  onClick={(event) => toggleThemeWithTransition(option.value, setTheme, event)}
                  aria-pressed={selected}
                >
                  <span className={cn('ios-symbol ios-symbol-sm', option.symbolClass)}>
                    <OptionIcon className="h-[18px] w-[18px]" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] font-medium leading-5 text-foreground">
                      {option.label}
                    </span>
                    <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                      {option.description}
                    </span>
                  </span>
                  {selected && <Check className="motion-selection h-4 w-4 shrink-0 text-primary" />}
                </button>
              )
            })}
          </div>
        </PopoverContent>
      </Popover>

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
              输入初始配置时设置的密码继续访问控制台。
            </p>
          </div>
        </header>

        <form onSubmit={handleSubmit} className="space-y-4" aria-busy={isValidating}>
          <input
            type="text"
            name="username"
            autoComplete="username"
            value="RiyaBot Console"
            readOnly
            tabIndex={-1}
            aria-hidden="true"
            className="sr-only"
          />
          <div className="ios-group overflow-hidden">
            <div className="ios-row min-h-[64px] gap-3 px-4 py-2">
              <KeyRound className="h-5 w-5 shrink-0 text-muted-foreground" strokeWidth={2} />
              <label
                htmlFor="password"
                className="shrink-0 text-[17px] font-medium leading-snug text-foreground"
              >
                密码
              </label>
              <Input
                ref={passwordInputRef}
                id="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="请输入密码"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value)
                  if (error) setError('')
                }}
                className={cn(
                  'h-10 min-w-0 flex-1 border-0 bg-transparent px-0 text-right text-[17px] shadow-none placeholder:text-muted-foreground/70 focus-visible:ring-0 focus-visible:ring-offset-0',
                  error && 'text-destructive placeholder:text-destructive/60'
                )}
                disabled={isValidating}
                autoComplete="current-password"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? 'auth-password-error' : undefined}
                autoFocus
              />
              <button
                type="button"
                className="ios-touch grid h-11 w-11 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-muted/70"
                onClick={() => setShowPassword((visible) => !visible)}
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
                aria-pressed={showPassword}
                title={showPassword ? '隐藏密码' : '显示密码'}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>

            {error && (
              <div
                id="auth-password-error"
                className="ios-row bg-destructive/5 text-destructive flex items-start gap-3 px-4 py-3 text-sm leading-relaxed"
                role="alert"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
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
                <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
                登录中...
              </>
            ) : (
              '登录'
            )}
          </Button>
        </form>
      </main>

      <p className="pb-[max(0.25rem,env(safe-area-inset-bottom))] text-center text-[11px] leading-relaxed text-muted-foreground">
        {APP_FULL_NAME}
      </p>
    </div>
  )
}
