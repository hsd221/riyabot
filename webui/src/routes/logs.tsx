import { useState, useRef, useEffect, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import {
  Calendar as CalendarIcon,
  Check,
  ChevronRight,
  Download,
  Filter,
  Radio,
  Pause,
  Play,
  RefreshCw,
  Search,
  Trash2,
  Type,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { logWebSocket, type LogEntry } from '@/lib/log-websocket'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

// 字号配置
type FontSize = 'xs' | 'sm' | 'base'
const fontSizeConfig: Record<
  FontSize,
  { label: string; desktopRowHeight: number; mobileRowHeight: number; class: string }
> = {
  xs: { label: '小', desktopRowHeight: 34, mobileRowHeight: 88, class: 'text-[10px] sm:text-xs' },
  sm: { label: '中', desktopRowHeight: 42, mobileRowHeight: 96, class: 'text-xs sm:text-sm' },
  base: { label: '大', desktopRowHeight: 52, mobileRowHeight: 106, class: 'text-sm sm:text-base' },
}

const LOG_LEVEL_OPTIONS = [
  { value: 'all', label: '全部级别', description: '显示所有日志级别' },
  { value: 'DEBUG', label: 'DEBUG', description: '调试信息' },
  { value: 'INFO', label: 'INFO', description: '常规运行信息' },
  { value: 'WARNING', label: 'WARNING', description: '需要关注的警告' },
  { value: 'ERROR', label: 'ERROR', description: '运行错误' },
  { value: 'CRITICAL', label: 'CRITICAL', description: '严重错误' },
] as const

export function LogViewerPage() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [levelFilter, setLevelFilter] = useState<string>('all')
  const [moduleFilter, setModuleFilter] = useState<string>('all')
  const [dateFrom, setDateFrom] = useState<Date | undefined>(undefined)
  const [dateTo, setDateTo] = useState<Date | undefined>(undefined)
  const [autoScroll, setAutoScroll] = useState(true)
  const [connected, setConnected] = useState(false)
  const [fontSize, setFontSize] = useState<FontSize>('xs') // 默认使用小字号以显示更多信息
  const [lineSpacing, setLineSpacing] = useState(4) // 行间距，默认4px（紧凑）
  const [levelDialogOpen, setLevelDialogOpen] = useState(false)
  const [moduleDialogOpen, setModuleDialogOpen] = useState(false)
  const [controlsDialogOpen, setControlsDialogOpen] = useState(false)
  const [isMobileViewport, setIsMobileViewport] = useState(false)
  const parentRef = useRef<HTMLDivElement>(null)

  // 订阅全局 WebSocket 连接
  useEffect(() => {
    // 初始化时加载缓存的日志
    const cachedLogs = logWebSocket.getAllLogs()
    setLogs(cachedLogs)

    // 订阅日志消息 - 直接使用全局缓存而不是组件状态
    const unsubscribeLogs = logWebSocket.onLog(() => {
      // 每次收到新日志，重新从全局缓存加载
      setLogs(logWebSocket.getAllLogs())
    })

    // 订阅连接状态
    const unsubscribeConnection = logWebSocket.onConnectionChange((isConnected) => {
      setConnected(isConnected)
    })

    // 清理订阅
    return () => {
      unsubscribeLogs()
      unsubscribeConnection()
    }
  }, [])

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 639px)')
    const updateViewport = () => setIsMobileViewport(mediaQuery.matches)

    updateViewport()
    mediaQuery.addEventListener('change', updateViewport)
    return () => mediaQuery.removeEventListener('change', updateViewport)
  }, [])

  // 获取所有唯一的模块名（过滤掉空字符串）
  const uniqueModules = useMemo(() => {
    const modules = new Set(logs.map((log) => log.module).filter((m) => m && m.trim() !== ''))
    return Array.from(modules).sort()
  }, [logs])

  // 日志级别颜色映射
  const getLevelColor = (level: LogEntry['level']) => {
    switch (level) {
      case 'DEBUG':
        return 'text-muted-foreground'
      case 'INFO':
        return 'text-primary'
      case 'WARNING':
        return 'text-orange-600 dark:text-orange-400'
      case 'ERROR':
        return 'text-red-600 dark:text-red-500'
      case 'CRITICAL':
        return 'text-red-700 dark:text-red-400 font-semibold'
      default:
        return 'text-foreground'
    }
  }

  const getLevelBgColor = (level: LogEntry['level']) => {
    switch (level) {
      case 'DEBUG':
        return 'bg-transparent'
      case 'INFO':
        return 'bg-[rgb(0_122_255_/_0.035)]'
      case 'WARNING':
        return 'bg-[rgb(255_149_0_/_0.055)]'
      case 'ERROR':
        return 'bg-[rgb(255_59_48_/_0.06)]'
      case 'CRITICAL':
        return 'bg-[rgb(255_59_48_/_0.09)]'
      default:
        return 'bg-transparent'
    }
  }

  const getLevelPillClass = (level: LogEntry['level']) => {
    switch (level) {
      case 'DEBUG':
        return 'bg-muted text-muted-foreground'
      case 'INFO':
        return 'bg-[rgb(0_122_255_/_0.12)] text-[#0066CC] dark:text-[#66B2FF]'
      case 'WARNING':
        return 'bg-[rgb(255_149_0_/_0.14)] text-[#B06000] dark:text-[#FFD099]'
      case 'ERROR':
        return 'bg-[rgb(255_59_48_/_0.14)] text-[#C9342B] dark:text-[#FF6961]'
      case 'CRITICAL':
        return 'bg-[rgb(255_59_48_/_0.18)] text-[#A82620] dark:text-[#FF8A83]'
      default:
        return 'bg-muted text-muted-foreground'
    }
  }

  // 刷新日志（刷新页面）
  const handleRefresh = () => {
    window.location.reload()
  }

  // 清空日志
  const handleClear = () => {
    logWebSocket.clearLogs() // 清空全局缓存
    setLogs([])
  }

  // 导出日志为 TXT 格式
  const handleExport = () => {
    // 格式化日志为文本
    const logText = filteredLogs
      .map((log) => `${log.timestamp} [${log.level.padEnd(8)}] [${log.module}] ${log.message}`)
      .join('\n')

    const dataBlob = new Blob([logText], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(dataBlob)
    const link = document.createElement('a')
    link.href = url
    link.download = `logs-${format(new Date(), 'yyyy-MM-dd-HHmmss')}.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

  // 切换自动滚动
  const toggleAutoScroll = () => {
    setAutoScroll(!autoScroll)
  }

  // 清除时间筛选
  const clearDateFilter = () => {
    setDateFrom(undefined)
    setDateTo(undefined)
  }

  // 过滤日志
  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      // 搜索过滤
      const matchesSearch =
        searchQuery === '' ||
        log.message.toLowerCase().includes(searchQuery.toLowerCase()) ||
        log.module.toLowerCase().includes(searchQuery.toLowerCase())

      // 级别过滤
      const matchesLevel = levelFilter === 'all' || log.level === levelFilter

      // 模块过滤
      const matchesModule = moduleFilter === 'all' || log.module === moduleFilter

      // 时间过滤
      let matchesDate = true
      if (dateFrom || dateTo) {
        const logDate = new Date(log.timestamp)
        if (dateFrom) {
          const fromDate = new Date(dateFrom)
          fromDate.setHours(0, 0, 0, 0)
          matchesDate = matchesDate && logDate >= fromDate
        }
        if (dateTo) {
          const toDate = new Date(dateTo)
          toDate.setHours(23, 59, 59, 999)
          matchesDate = matchesDate && logDate <= toDate
        }
      }

      return matchesSearch && matchesLevel && matchesModule && matchesDate
    })
  }, [logs, searchQuery, levelFilter, moduleFilter, dateFrom, dateTo])

  const activeLevelLabel =
    LOG_LEVEL_OPTIONS.find((option) => option.value === levelFilter)?.label ?? levelFilter
  const activeModuleLabel = moduleFilter === 'all' ? '全部模块' : moduleFilter
  const dateRangeLabel =
    dateFrom || dateTo
      ? `${dateFrom ? format(dateFrom, 'MM-dd') : '不限'} 至 ${
          dateTo ? format(dateTo, 'MM-dd') : '不限'
        }`
      : '不限时间'

  // 虚拟滚动配置 - 根据字号和行间距动态计算行高
  const estimatedRowHeight =
    (isMobileViewport
      ? fontSizeConfig[fontSize].mobileRowHeight
      : fontSizeConfig[fontSize].desktopRowHeight) + lineSpacing

  const rowVirtualizer = useVirtualizer({
    count: filteredLogs.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimatedRowHeight,
    overscan: 50, // 增加预渲染数量以减少快速滚动时的空白
  })

  // 用于追踪是否是程序触发的滚动
  const isAutoScrollingRef = useRef(false)
  // 用于追踪上一次的日志数量
  const prevLogCountRef = useRef(filteredLogs.length)
  // 首次加载缓存日志时保持列表从顶部开始，避免移动端圆角卡片顶端出现半截日志行。
  const initialLogLoadHandledRef = useRef(false)

  // 检测用户滚动行为，当用户向上滚动时禁用自动滚动
  useEffect(() => {
    const scrollElement = parentRef.current
    if (!scrollElement) return

    const handleScroll = () => {
      // 如果是程序触发的滚动，忽略
      if (isAutoScrollingRef.current) return

      const { scrollTop, scrollHeight, clientHeight } = scrollElement
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight

      // 如果距离底部超过 100px，说明用户在向上查看，禁用自动滚动
      if (distanceFromBottom > 100 && autoScroll) {
        setAutoScroll(false)
      }
      // 如果用户滚动到接近底部（小于 50px），可以重新启用自动滚动
      else if (distanceFromBottom < 50 && !autoScroll) {
        setAutoScroll(true)
      }
    }

    scrollElement.addEventListener('scroll', handleScroll, { passive: true })
    return () => scrollElement.removeEventListener('scroll', handleScroll)
  }, [autoScroll])

  // 自动滚动到底部
  useEffect(() => {
    // 只有在日志数量增加时才滚动（避免删除日志时触发）
    const logCountIncreased = filteredLogs.length > prevLogCountRef.current

    if (!initialLogLoadHandledRef.current) {
      initialLogLoadHandledRef.current = filteredLogs.length > 0
      prevLogCountRef.current = filteredLogs.length
      return
    }

    prevLogCountRef.current = filteredLogs.length

    if (autoScroll && filteredLogs.length > 0 && logCountIncreased) {
      isAutoScrollingRef.current = true
      rowVirtualizer.scrollToIndex(filteredLogs.length - 1, {
        align: 'end',
        behavior: 'auto',
      })
      // 稍后重置标志，给滚动事件处理一些时间
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          isAutoScrollingRef.current = false
        })
      })
    }
  }, [filteredLogs.length, autoScroll, rowVirtualizer])

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex-shrink-0 space-y-4 px-5 py-5 sm:p-4 lg:p-6">
        {/* 标题 */}
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">日志查看器</h1>
            <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
              实时查看和分析主程序运行日志
            </p>
          </div>
          {/* 连接状态指示器 */}
          <div className="ios-group flex min-h-[52px] items-center gap-3 rounded-full px-3 py-2 sm:min-w-[168px]">
            <span
              className={cn(
                'ios-symbol ios-symbol-sm',
                connected ? 'ios-symbol-green' : 'ios-symbol-red'
              )}
            >
              <Radio className="h-4 w-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-[14px] font-medium leading-5">
                {connected ? '已连接' : '未连接'}
              </span>
              <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                {connected ? '实时日志流' : '等待日志流'}
              </span>
            </span>
          </div>
        </div>

        {/* 移动端控制栏 */}
        <div className="space-y-3 sm:hidden">
          <div className="ios-group overflow-hidden">
            <div className="relative flex min-h-[58px] items-center gap-3 px-4 py-3 after:absolute after:bottom-0 after:left-16 after:right-0 after:h-px after:bg-border/55">
              <Search className="h-5 w-5 shrink-0 text-muted-foreground" />
              <Input
                placeholder="搜索日志..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-9 border-0 bg-transparent px-0 text-[15px] shadow-none focus-visible:ring-0"
              />
            </div>

            <Dialog open={levelDialogOpen} onOpenChange={setLevelDialogOpen}>
              <DialogTrigger asChild>
                <button className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0">
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">日志级别</span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      按严重程度筛选
                    </span>
                  </span>
                  <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <span className="truncate text-[15px] leading-5 text-foreground">
                      {activeLevelLabel}
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0" />
                  </span>
                </button>
              </DialogTrigger>
              <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
                <DialogHeader className="px-5 pt-5">
                  <DialogTitle>日志级别</DialogTitle>
                  <DialogDescription>选择要显示的日志级别</DialogDescription>
                </DialogHeader>
                <div className="px-5">
                  <div className="ios-group overflow-hidden">
                    {LOG_LEVEL_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                        onClick={() => {
                          setLevelFilter(option.value)
                          setLevelDialogOpen(false)
                        }}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-[16px] font-medium leading-6">
                            {option.label}
                          </span>
                          <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                            {option.description}
                          </span>
                        </span>
                        {levelFilter === option.value ? (
                          <Check className="h-4 w-4 shrink-0 text-primary" />
                        ) : (
                          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </DialogContent>
            </Dialog>

            <Dialog open={moduleDialogOpen} onOpenChange={setModuleDialogOpen}>
              <DialogTrigger asChild>
                <button className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0">
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">模块</span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      按日志来源筛选
                    </span>
                  </span>
                  <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <span className="max-w-[9rem] truncate text-[15px] leading-5 text-foreground">
                      {activeModuleLabel}
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0" />
                  </span>
                </button>
              </DialogTrigger>
              <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
                <DialogHeader className="px-5 pt-5">
                  <DialogTitle>日志模块</DialogTitle>
                  <DialogDescription>选择要显示的日志来源</DialogDescription>
                </DialogHeader>
                <div className="ios-scrollbar-none max-h-[58vh] overflow-y-auto px-5">
                  <div className="ios-group overflow-hidden">
                    {['all', ...uniqueModules].map((module) => (
                      <button
                        key={module}
                        type="button"
                        className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                        onClick={() => {
                          setModuleFilter(module)
                          setModuleDialogOpen(false)
                        }}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-[16px] font-medium leading-6">
                            {module === 'all' ? '全部模块' : module}
                          </span>
                          <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                            {module === 'all' ? '显示所有来源' : '仅显示此模块'}
                          </span>
                        </span>
                        {moduleFilter === module ? (
                          <Check className="h-4 w-4 shrink-0 text-primary" />
                        ) : (
                          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </DialogContent>
            </Dialog>

            <Dialog open={controlsDialogOpen} onOpenChange={setControlsDialogOpen}>
              <DialogTrigger asChild>
                <button className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0">
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">日志控制</span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      {dateRangeLabel} · {autoScroll ? '自动滚动' : '已暂停'} ·{' '}
                      {filteredLogs.length}/{logs.length}
                    </span>
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </button>
              </DialogTrigger>
              <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
                <DialogHeader className="px-5 pt-5">
                  <DialogTitle>日志控制</DialogTitle>
                  <DialogDescription>调整时间范围、操作和显示方式</DialogDescription>
                </DialogHeader>
                <div className="ios-scrollbar-none max-h-[58vh] space-y-4 overflow-y-auto px-5">
                  <div className="ios-group overflow-hidden">
                    <div className="ios-row min-h-[72px] py-3">
                      <span className="min-w-0">
                        <span className="block text-[15px] font-medium leading-5">时间范围</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          {dateRangeLabel}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1">
                        <Popover>
                          <PopoverTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-9 rounded-full px-3 focus-visible:bg-accent/70 focus-visible:ring-0"
                            >
                              开始
                            </Button>
                          </PopoverTrigger>
                          <PopoverContent className="w-auto p-0" align="end">
                            <Calendar
                              mode="single"
                              selected={dateFrom}
                              onSelect={setDateFrom}
                              initialFocus
                              locale={zhCN}
                            />
                          </PopoverContent>
                        </Popover>
                        <Popover>
                          <PopoverTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-9 rounded-full px-3 focus-visible:bg-accent/70 focus-visible:ring-0"
                            >
                              结束
                            </Button>
                          </PopoverTrigger>
                          <PopoverContent className="w-auto p-0" align="end">
                            <Calendar
                              mode="single"
                              selected={dateTo}
                              onSelect={setDateTo}
                              initialFocus
                              locale={zhCN}
                            />
                          </PopoverContent>
                        </Popover>
                        {(dateFrom || dateTo) && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={clearDateFilter}
                            className="h-9 w-9 rounded-full"
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        )}
                      </span>
                    </div>
                    <div className="ios-row min-h-[58px] py-3">
                      <span className="min-w-0">
                        <span className="block text-[15px] font-medium leading-5">自动滚动</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          新日志出现时保持在底部
                        </span>
                      </span>
                      <Switch checked={autoScroll} onCheckedChange={setAutoScroll} />
                    </div>
                    <div className="ios-row min-h-[58px] py-3">
                      <span className="text-[15px] font-medium leading-5">操作</span>
                      <span className="flex items-center gap-2">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={handleRefresh}
                          className="h-9 w-9 rounded-full"
                        >
                          <RefreshCw className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={handleClear}
                          className="h-9 w-9 rounded-full"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={handleExport}
                          className="h-9 w-9 rounded-full"
                        >
                          <Download className="h-4 w-4" />
                        </Button>
                      </span>
                    </div>
                    <div className="ios-row min-h-[58px] py-3">
                      <span className="text-[15px] font-medium leading-5">当前显示</span>
                      <span className="font-mono text-[14px] leading-5 text-muted-foreground">
                        {filteredLogs.length} / {logs.length}
                      </span>
                    </div>
                  </div>

                  <div className="ios-group overflow-hidden">
                    <div className="ios-row min-h-[58px] py-3">
                      <span className="flex items-center gap-2 text-[15px] font-medium leading-5">
                        <Type className="h-4 w-4 text-muted-foreground" />
                        字号
                      </span>
                      <span className="flex gap-1">
                        {(Object.keys(fontSizeConfig) as FontSize[]).map((size) => (
                          <Button
                            key={size}
                            variant={fontSize === size ? 'default' : 'ghost'}
                            size="sm"
                            onClick={() => setFontSize(size)}
                            className="h-8 rounded-full px-3 text-xs"
                          >
                            {fontSizeConfig[size].label}
                          </Button>
                        ))}
                      </span>
                    </div>
                    <div className="ios-row min-h-[58px] py-3">
                      <span className="text-[15px] font-medium leading-5">行距</span>
                      <span className="flex min-w-0 flex-1 items-center gap-3 pl-4">
                        <Slider
                          value={[lineSpacing]}
                          onValueChange={([value]) => setLineSpacing(value)}
                          min={0}
                          max={12}
                          step={2}
                          className="min-w-0 flex-1"
                        />
                        <span className="w-9 text-right text-xs text-muted-foreground">
                          {lineSpacing}px
                        </span>
                      </span>
                    </div>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        </div>

        {/* 控制栏 */}
        <div className="ios-group hidden overflow-hidden p-4 sm:block">
          <div className="flex flex-col gap-3 sm:gap-4">
            {/* 第一行：搜索和筛选 */}
            <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
              {/* 搜索框 */}
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="搜索日志..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-10 rounded-[12px] border-0 bg-muted/75 pl-9 text-sm shadow-none focus-visible:ring-0"
                />
              </div>

              {/* 日志级别筛选 */}
              <Select value={levelFilter} onValueChange={setLevelFilter}>
                <SelectTrigger className="h-10 w-full rounded-[12px] border-0 bg-muted/75 text-sm shadow-none sm:w-[140px] lg:w-[180px]">
                  <Filter className="mr-2 h-4 w-4" />
                  <SelectValue placeholder="级别" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部级别</SelectItem>
                  <SelectItem value="DEBUG">DEBUG</SelectItem>
                  <SelectItem value="INFO">INFO</SelectItem>
                  <SelectItem value="WARNING">WARNING</SelectItem>
                  <SelectItem value="ERROR">ERROR</SelectItem>
                  <SelectItem value="CRITICAL">CRITICAL</SelectItem>
                </SelectContent>
              </Select>

              {/* 模块筛选 */}
              <Select value={moduleFilter} onValueChange={setModuleFilter}>
                <SelectTrigger className="h-10 w-full rounded-[12px] border-0 bg-muted/75 text-sm shadow-none sm:w-[160px] lg:w-[200px]">
                  <Filter className="mr-2 h-4 w-4" />
                  <SelectValue placeholder="模块" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部模块</SelectItem>
                  {uniqueModules.map((module) => (
                    <SelectItem key={module} value={module}>
                      {module}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* 第二行：时间筛选 */}
            <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
              {/* 开始日期 */}
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className={cn(
                      'h-10 w-full justify-start rounded-full text-left font-normal sm:w-[200px] lg:w-[240px]',
                      !dateFrom && 'text-muted-foreground'
                    )}
                  >
                    <CalendarIcon className="mr-2 h-4 w-4" />
                    <span className="text-xs sm:text-sm">
                      {dateFrom ? format(dateFrom, 'PPP', { locale: zhCN }) : '开始日期'}
                    </span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={dateFrom}
                    onSelect={setDateFrom}
                    initialFocus
                    locale={zhCN}
                  />
                </PopoverContent>
              </Popover>

              {/* 结束日期 */}
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className={cn(
                      'h-10 w-full justify-start rounded-full text-left font-normal sm:w-[200px] lg:w-[240px]',
                      !dateTo && 'text-muted-foreground'
                    )}
                  >
                    <CalendarIcon className="mr-2 h-4 w-4" />
                    <span className="text-xs sm:text-sm">
                      {dateTo ? format(dateTo, 'PPP', { locale: zhCN }) : '结束日期'}
                    </span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={dateTo}
                    onSelect={setDateTo}
                    initialFocus
                    locale={zhCN}
                  />
                </PopoverContent>
              </Popover>

              {/* 清除时间筛选 */}
              {(dateFrom || dateTo) && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={clearDateFilter}
                  className="h-10 w-full rounded-full sm:w-auto"
                >
                  <X className="h-4 w-4 sm:mr-2" />
                  <span className="hidden text-sm sm:inline">清除时间筛选</span>
                  <span className="text-sm sm:hidden">清除</span>
                </Button>
              )}
            </div>

            {/* 第三行：操作按钮 */}
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
              <div className="flex flex-wrap gap-2">
                <Button
                  variant={autoScroll ? 'default' : 'outline'}
                  size="sm"
                  onClick={toggleAutoScroll}
                  className="h-10 flex-1 rounded-full sm:flex-none"
                >
                  {autoScroll ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  <span className="ml-2 text-sm">{autoScroll ? '自动滚动' : '已暂停'}</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRefresh}
                  className="h-10 flex-1 rounded-full sm:flex-none"
                >
                  <RefreshCw className="h-4 w-4" />
                  <span className="ml-2 text-sm">刷新</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleClear}
                  className="h-10 flex-1 rounded-full sm:flex-none"
                >
                  <Trash2 className="h-4 w-4" />
                  <span className="ml-2 text-sm">清空</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleExport}
                  className="h-10 flex-1 rounded-full sm:flex-none"
                >
                  <Download className="h-4 w-4" />
                  <span className="ml-2 text-sm">导出</span>
                </Button>
              </div>
              <div className="hidden flex-1 sm:block" />
              <div className="flex items-center justify-center text-xs text-muted-foreground sm:justify-end sm:text-sm">
                <span className="font-mono">
                  {filteredLogs.length} / {logs.length}
                </span>
                <span className="ml-1">条日志</span>
              </div>
            </div>

            {/* 第四行：显示设置 */}
            <div className="flex flex-col gap-3 border-t border-border/40 pt-3 sm:flex-row sm:items-center sm:gap-6">
              {/* 字号调整 */}
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Type className="h-4 w-4" />
                  <span>字号</span>
                </div>
                <div className="flex gap-1">
                  {(Object.keys(fontSizeConfig) as FontSize[]).map((size) => (
                    <Button
                      key={size}
                      variant={fontSize === size ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setFontSize(size)}
                      className="h-8 rounded-full px-3 text-xs"
                    >
                      {fontSizeConfig[size].label}
                    </Button>
                  ))}
                </div>
              </div>

              {/* 行间距调整 */}
              <div className="flex max-w-xs flex-1 items-center gap-3">
                <span className="whitespace-nowrap text-sm text-muted-foreground">行距</span>
                <Slider
                  value={[lineSpacing]}
                  onValueChange={([value]) => setLineSpacing(value)}
                  min={0}
                  max={12}
                  step={2}
                  className="flex-1"
                />
                <span className="w-8 text-xs text-muted-foreground">{lineSpacing}px</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 日志终端 - 使用虚拟滚动，填充剩余空间 */}
      <div className="flex min-h-0 flex-1 flex-col px-5 pb-5 sm:px-4 sm:pb-4 lg:px-6 lg:pb-6">
        <p className="mb-2 px-1 text-[13px] font-medium leading-5 text-muted-foreground sm:hidden">
          实时日志
        </p>
        <div className="ios-group min-h-0 flex-1 overflow-hidden">
          <div ref={parentRef} className="ios-scrollbar-none h-full overflow-auto">
            <div
              className={cn('relative sm:font-mono', fontSizeConfig[fontSize].class)}
              style={{
                height: filteredLogs.length === 0 ? '100%' : `${rowVirtualizer.getTotalSize()}px`,
              }}
            >
              {filteredLogs.length === 0 ? (
                <div className="ios-empty-state h-full min-h-[260px]">
                  <span className="ios-empty-illustration">
                    <Radio className="h-7 w-7 text-primary" />
                  </span>
                  <span className="space-y-1.5">
                    <span className="block text-[15px] font-semibold leading-5 text-foreground">
                      暂无日志数据
                    </span>
                    <span className="block text-[13px] leading-5 text-muted-foreground">
                      新日志出现后会自动显示在这里
                    </span>
                  </span>
                </div>
              ) : (
                rowVirtualizer.getVirtualItems().map((virtualRow) => {
                  const log = filteredLogs[virtualRow.index]
                  return (
                    <div
                      key={virtualRow.key}
                      data-index={virtualRow.index}
                      ref={rowVirtualizer.measureElement}
                      className={cn(
                        'absolute left-0 top-0 w-full px-4 transition-colors after:absolute after:bottom-0 after:left-16 after:right-0 after:h-px after:bg-border/55 last:after:hidden hover:bg-accent/45 sm:border-b sm:border-border/45 sm:px-5 sm:after:hidden',
                        getLevelBgColor(log.level)
                      )}
                      style={{
                        transform: `translateY(${virtualRow.start}px)`,
                        minHeight: `${estimatedRowHeight}px`,
                        paddingTop: `${lineSpacing / 2}px`,
                        paddingBottom: `${lineSpacing / 2}px`,
                      }}
                    >
                      {/* 移动端：列表布局 */}
                      <div className="flex flex-col gap-1.5 py-2 sm:hidden">
                        <div className="flex items-center justify-between gap-3">
                          <span className="min-w-0 truncate font-mono text-[12px] leading-4 text-muted-foreground">
                            {log.timestamp}
                          </span>
                          <span
                            className={cn(
                              'shrink-0 rounded-full px-2 py-0.5 font-mono text-[11px] font-semibold leading-4',
                              getLevelPillClass(log.level)
                            )}
                          >
                            {log.level}
                          </span>
                        </div>
                        <div className="truncate text-[13px] font-medium leading-5 text-muted-foreground">
                          {log.module || 'system'}
                        </div>
                        <div className="whitespace-pre-wrap break-words text-[15px] leading-6 text-foreground">
                          {log.message}
                        </div>
                      </div>

                      {/* 平板/桌面端：水平布局 */}
                      <div className="hidden min-h-[34px] items-center gap-2 sm:flex">
                        {/* 时间戳 */}
                        <span className="w-[130px] flex-shrink-0 text-muted-foreground lg:w-[160px]">
                          {log.timestamp}
                        </span>

                        {/* 日志级别 */}
                        <span
                          className={cn(
                            'w-[65px] flex-shrink-0 font-semibold lg:w-[75px]',
                            getLevelColor(log.level)
                          )}
                        >
                          [{log.level}]
                        </span>

                        {/* 模块名 */}
                        <span className="w-[100px] flex-shrink-0 truncate text-primary lg:w-[130px]">
                          {log.module}
                        </span>

                        {/* 消息内容 */}
                        <span className="text-foreground/88 flex-1 whitespace-pre-wrap break-words">
                          {log.message}
                        </span>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
