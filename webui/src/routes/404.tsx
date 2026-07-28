import { useNavigate } from '@tanstack/react-router'
import { ArrowLeft, Home, SearchX } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <div className="ios-page ios-app-min-height flex items-center justify-center">
      <main
        className="ios-card w-full max-w-lg space-y-6 p-6 text-center sm:p-8"
        aria-labelledby="not-found-title"
      >
        <span className="ios-symbol ios-symbol-blue mx-auto flex h-16 w-16 rounded-[20px]">
          <SearchX className="h-8 w-8" />
        </span>

        <div className="space-y-2">
          <p className="text-[13px] font-semibold uppercase tracking-[0.12em] text-primary">404</p>
          <h1
            id="not-found-title"
            className="text-[28px] font-semibold leading-tight text-foreground"
          >
            页面未找到
          </h1>
          <p className="mx-auto max-w-sm text-[15px] leading-6 text-muted-foreground">
            这个地址可能已更改、被移除，或输入有误。可以返回首页继续浏览。
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button onClick={() => navigate({ to: '/' })} className="h-11 flex-1">
            <Home className="mr-2 h-4 w-4" />
            返回首页
          </Button>
          <Button variant="outline" onClick={() => window.history.back()} className="h-11 flex-1">
            <ArrowLeft className="mr-2 h-4 w-4" />
            返回上一页
          </Button>
        </div>
      </main>
    </div>
  )
}
