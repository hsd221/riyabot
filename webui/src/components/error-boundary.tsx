import { Component, useState } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import {
  AlertTriangle,
  Bug,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Home,
  RefreshCw,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

interface StackFrame {
  functionName: string
  fileName: string
  lineNumber: string
  columnNumber: string
  raw: string
}

const isDevelopment = import.meta.env.DEV

function parseStackTrace(stack: string): StackFrame[] {
  const lines = stack.split('\n').slice(1)
  const frames: StackFrame[] = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('at ')) continue

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

function ErrorDetails({ error, errorInfo }: { error: Error; errorInfo: ErrorInfo | null }) {
  const [isStackOpen, setIsStackOpen] = useState(false)
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
    `.trim()

    try {
      await navigator.clipboard.writeText(errorText)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch (copyError) {
      console.error('复制错误详情失败:', copyError)
    }
  }

  return (
    <div className="space-y-3 rounded-[18px] border border-border/60 bg-muted/30 p-3 text-left">
      <div className="text-destructive flex items-start gap-3 text-sm">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p className="min-w-0 break-words font-mono">
          <span className="font-semibold">{error.name}：</span> {error.message}
        </p>
      </div>

      {stackFrames.length > 0 && (
        <Collapsible open={isStackOpen} onOpenChange={setIsStackOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" className="h-11 w-full justify-between px-3">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <Bug className="h-4 w-4" />
                Stack Trace（{stackFrames.length}）
              </span>
              {isStackOpen ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ScrollArea className="h-[280px] rounded-[14px] border border-border/60 bg-background/70">
              <ol className="space-y-1 p-3">
                {stackFrames.map((frame, index) => (
                  <li
                    key={`${frame.raw}-${index}`}
                    className="rounded-[10px] p-2 font-mono text-xs"
                  >
                    <span className="font-medium text-primary">{frame.functionName}</span>
                    {frame.fileName && (
                      <span className="mt-0.5 block break-all text-muted-foreground">
                        {frame.fileName}
                        {frame.lineNumber && `:${frame.lineNumber}:${frame.columnNumber}`}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            </ScrollArea>
          </CollapsibleContent>
        </Collapsible>
      )}

      {errorInfo?.componentStack && (
        <Collapsible open={isComponentStackOpen} onOpenChange={setIsComponentStackOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" className="h-11 w-full justify-between px-3">
              <span className="text-sm font-semibold">Component Stack</span>
              {isComponentStackOpen ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ScrollArea className="h-[200px] rounded-[14px] border border-border/60 bg-background/70">
              <pre className="whitespace-pre-wrap p-3 font-mono text-xs text-muted-foreground">
                {errorInfo.componentStack}
              </pre>
            </ScrollArea>
          </CollapsibleContent>
        </Collapsible>
      )}

      <Button variant="outline" onClick={copyErrorInfo} className="h-11 w-full">
        {copied ? (
          <Check className="text-success mr-2 h-4 w-4" />
        ) : (
          <Copy className="mr-2 h-4 w-4" />
        )}
        {copied ? '已复制错误详情' : '复制错误详情'}
      </Button>
    </div>
  )
}

function ErrorFallback({ error, errorInfo }: { error: Error; errorInfo: ErrorInfo | null }) {
  return (
    <div className="ios-page ios-app-min-height flex items-center justify-center">
      <main
        className="ios-card w-full max-w-xl space-y-6 p-6 text-center sm:p-8"
        role="alert"
        aria-labelledby="application-error-title"
      >
        <span className="ios-symbol ios-symbol-red mx-auto flex h-16 w-16 rounded-[20px]">
          <AlertTriangle className="h-8 w-8" />
        </span>
        <div className="space-y-2">
          <h1 id="application-error-title" className="text-2xl font-semibold text-foreground">
            页面出现了问题
          </h1>
          <p className="text-[15px] leading-6 text-muted-foreground">
            当前页面未能正常显示。可以先刷新页面；如果问题持续存在，请返回首页后重试。
          </p>
        </div>

        {isDevelopment && <ErrorDetails error={error} errorInfo={errorInfo} />}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button onClick={() => window.location.reload()} className="h-11 flex-1">
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新页面
          </Button>
          <Button
            onClick={() => {
              window.location.href = '/'
            }}
            variant="outline"
            className="h-11 flex-1"
          >
            <Home className="mr-2 h-4 w-4" />
            返回首页
          </Button>
        </div>

        {!isDevelopment && (
          <p className="text-xs leading-5 text-muted-foreground">
            诊断详情已记录在浏览器控制台，不会在生产页面中显示。
          </p>
        )}
      </main>
    </div>
  )
}

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
      if (this.props.fallback) return this.props.fallback
      return <ErrorFallback error={this.state.error} errorInfo={this.state.errorInfo} />
    }

    return this.props.children
  }
}

export function RouteErrorBoundary({ error }: { error: Error }) {
  return <ErrorFallback error={error} errorInfo={null} />
}
