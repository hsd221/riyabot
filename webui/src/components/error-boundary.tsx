import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import {
  AlertTriangle,
  RefreshCw,
  Home,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Bug,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useState } from 'react'

const softRedTextClass = 'text-[rgb(174_37_31)] dark:text-[rgb(255_105_97)]'
const softGreenTextClass = 'text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
const softOrangeTextClass = 'text-[rgb(178_93_0)] dark:text-[rgb(255_159_10)]'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

// 解析堆栈信息为结构化数据
interface StackFrame {
  functionName: string
  fileName: string
  lineNumber: string
  columnNumber: string
  raw: string
}

function parseStackTrace(stack: string): StackFrame[] {
  const lines = stack.split('\n').slice(1) // 跳过第一行（错误消息）
  const frames: StackFrame[] = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('at ')) continue

    // 匹配格式: at functionName (fileName:line:column) 或 at fileName:line:column
    const match = trimmed.match(/at\s+(?:(.+?)\s+\()?(.+?):(\d+):(\d+)\)?$/)
    if (match) {
      frames.push({
        functionName: match[1] || '<anonymous>',
        fileName: match[2],
        lineNumber: match[3],
        columnNumber: match[4],
        raw: trimmed,
      })
    } else {
      frames.push({
        functionName: '<unknown>',
        fileName: '',
        lineNumber: '',
        columnNumber: '',
        raw: trimmed,
      })
    }
  }

  return frames
}

// 错误详情展示组件（函数组件，用于使用 hooks）
function ErrorDetails({ error, errorInfo }: { error: Error; errorInfo: ErrorInfo | null }) {
  const [isStackOpen, setIsStackOpen] = useState(true)
  const [isComponentStackOpen, setIsComponentStackOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const stackFrames = error.stack ? parseStackTrace(error.stack) : []

  const copyErrorInfo = async () => {
    const errorText = `
Error: ${error.name}
Message: ${error.message}

Stack Trace:
${error.stack || 'No stack trace available'}

Component Stack:
${errorInfo?.componentStack || 'No component stack available'}

URL: ${window.location.href}
User Agent: ${navigator.userAgent}
Time: ${new Date().toISOString()}
    `.trim()

    try {
      await navigator.clipboard.writeText(errorText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  return (
    <div className="space-y-4">
      {/* 错误消息 */}
      <Alert
        variant="destructive"
        className="border-[rgb(255_59_48_/_0.22)] bg-[rgb(255_59_48_/_0.08)]"
      >
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription className={`font-mono text-sm ${softRedTextClass}`}>
          <span className="font-semibold">{error.name}:</span> {error.message}
        </AlertDescription>
      </Alert>

      {/* 堆栈跟踪 */}
      {stackFrames.length > 0 && (
        <Collapsible open={isStackOpen} onOpenChange={setIsStackOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" className="h-auto w-full justify-between p-3">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <Bug className="h-4 w-4" />
                Stack Trace ({stackFrames.length} frames)
              </span>
              {isStackOpen ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ScrollArea className="h-[280px] rounded-[16px] border border-black/[0.035] bg-muted/30 dark:border-white/10">
              <div className="space-y-1 p-3">
                {stackFrames.map((frame, index) => (
                  <div
                    key={index}
                    className="rounded-[12px] p-2 font-mono text-xs transition-colors hover:bg-muted/50"
                  >
                    <div className="flex items-start gap-2">
                      <span className="w-6 flex-shrink-0 text-right text-muted-foreground">
                        {index + 1}.
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="font-medium text-primary">{frame.functionName}</span>
                        {frame.fileName && (
                          <div className="mt-0.5 break-all text-muted-foreground">
                            {frame.fileName}
                            {frame.lineNumber && (
                              <span className={softOrangeTextClass}>
                                :{frame.lineNumber}:{frame.columnNumber}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* 组件堆栈 */}
      {errorInfo?.componentStack && (
        <Collapsible open={isComponentStackOpen} onOpenChange={setIsComponentStackOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" className="h-auto w-full justify-between p-3">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <AlertTriangle className="h-4 w-4" />
                Component Stack
              </span>
              {isComponentStackOpen ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ScrollArea className="h-[200px] rounded-[16px] border border-black/[0.035] bg-muted/30 dark:border-white/10">
              <pre className="whitespace-pre-wrap p-3 font-mono text-xs text-muted-foreground">
                {errorInfo.componentStack}
              </pre>
            </ScrollArea>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* 复制按钮 */}
      <Button variant="outline" size="sm" onClick={copyErrorInfo} className="w-full">
        {copied ? (
          <>
            <Check className={`mr-2 h-4 w-4 ${softGreenTextClass}`} />
            已复制到剪贴板
          </>
        ) : (
          <>
            <Copy className="mr-2 h-4 w-4" />
            复制错误信息
          </>
        )}
      </Button>
    </div>
  )
}

// 错误回退 UI
function ErrorFallback({ error, errorInfo }: { error: Error; errorInfo: ErrorInfo | null }) {
  const handleGoHome = () => {
    window.location.href = '/'
  }

  const handleRefresh = () => {
    window.location.reload()
  }

  return (
    <div className="ios-page flex min-h-screen items-center justify-center">
      <Card className="ios-card w-full max-w-2xl">
        <CardHeader className="pb-2 text-center">
          <div className="ios-symbol ios-symbol-red mx-auto mb-4 h-16 w-16 rounded-[20px]">
            <AlertTriangle className="h-8 w-8" />
          </div>
          <CardTitle className="text-2xl font-semibold">页面出现了问题</CardTitle>
          <CardDescription className="mt-2 text-base">
            应用程序遇到了意外错误。您可以尝试刷新页面或返回首页。
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          <ErrorDetails error={error} errorInfo={errorInfo} />

          {/* 操作按钮 */}
          <div className="flex flex-col gap-2 pt-2 sm:flex-row">
            <Button onClick={handleRefresh} className="flex-1">
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新页面
            </Button>
            <Button onClick={handleGoHome} variant="outline" className="flex-1">
              <Home className="mr-2 h-4 w-4" />
              返回首页
            </Button>
          </div>

          {/* 提示信息 */}
          <p className="pt-2 text-center text-xs text-muted-foreground">
            如果问题持续存在，请将错误信息复制并反馈给开发者
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

// 错误边界类组件
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
    this.setState({ errorInfo })
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    })
  }

  render() {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return <ErrorFallback error={this.state.error} errorInfo={this.state.errorInfo} />
    }

    return this.props.children
  }
}

// 路由级别的错误边界组件（用于 TanStack Router）
export function RouteErrorBoundary({ error }: { error: Error }) {
  return <ErrorFallback error={error} errorInfo={null} />
}
