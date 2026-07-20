import { useEffect, useState, useCallback } from 'react'
import axios from 'axios'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ModelPieLegend } from '@/components/statistics/model-pie-legend'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Progress } from '@/components/ui/progress'
import { Switch } from '@/components/ui/switch'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  type ChartConfig,
} from '@/components/ui/chart'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import {
  Activity,
  TrendingUp,
  DollarSign,
  Clock,
  MessageSquare,
  Zap,
  Database,
  RefreshCw,
  Power,
  RotateCcw,
  FileText,
  Settings,
  Puzzle,
  Check,
  ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Link } from '@tanstack/react-router'
import { useToast } from '@/hooks/use-toast'

// 机器人状态接口
interface BotStatus {
  running: boolean
  uptime: number
  version: string
  start_time: string
}

interface StatisticsSummary {
  total_requests: number
  total_cost: number
  total_tokens: number
  online_time: number
  total_messages: number
  total_replies: number
  avg_response_time: number
  cost_per_hour: number
  tokens_per_hour: number
}

interface ModelStatistics {
  model_name: string
  request_count: number
  total_cost: number
  total_tokens: number
  avg_response_time: number
}

interface TimeSeriesData {
  timestamp: string
  requests: number
  cost: number
  tokens: number
}

interface RecentActivity {
  timestamp: string
  model: string
  request_type: string
  tokens: number
  cost: number
  time_cost: number
  status: string
}

interface DashboardData {
  summary: StatisticsSummary
  model_stats: ModelStatistics[]
  hourly_data: TimeSeriesData[]
  daily_data: TimeSeriesData[]
  recent_activity: RecentActivity[]
}

const iosChartPalette = [
  '#007AFF',
  '#34C759',
  '#FF9500',
  '#5856D6',
  '#FF2D55',
  '#5AC8FA',
  '#AF52DE',
  '#FFCC00',
]

// 使用接近 iOS 系统色的图表调色板，避免随机高饱和色破坏整体质感。
const generatePieColors = (count: number): string[] => {
  const colors: string[] = []
  for (let i = 0; i < count; i++) {
    colors.push(iosChartPalette[i % iosChartPalette.length])
  }
  return colors
}

const timeRangeOptions = [
  { value: 24, label: '24小时', description: '查看最近一天的统计数据' },
  { value: 168, label: '7天', description: '查看最近一周的统计数据' },
  { value: 720, label: '30天', description: '查看最近一个月的统计数据' },
]

const chartGridStroke = 'hsl(var(--muted-foreground) / 0.13)'
const chartAxisStroke = 'hsl(var(--muted-foreground) / 0.42)'
const chartAxisTick = { fill: 'hsl(var(--muted-foreground) / 0.72)', fontSize: 12 }

function ChartEmptyState({
  title = '暂无足够数据',
  description = '有新的统计记录后这里会显示变化趋势',
}: {
  title?: string
  description?: string
}) {
  return (
    <div className="ios-empty-state min-h-[260px] sm:min-h-[320px]">
      <div className="relative h-24 w-full max-w-[320px]" aria-hidden="true">
        <div className="absolute inset-x-0 bottom-4 border-t border-dashed border-muted-foreground/25" />
        <div className="absolute inset-x-3 bottom-5 h-14 rounded-[18px] border border-dashed border-primary/25 bg-primary/[0.035]" />
        <div className="absolute left-8 top-8 h-2 w-2 rounded-full bg-primary/40" />
        <div className="absolute left-[34%] top-12 h-2 w-2 rounded-full bg-primary/35" />
        <div className="absolute right-[28%] top-6 h-2 w-2 rounded-full bg-primary/50" />
        <div className="absolute right-10 top-10 h-2 w-2 rounded-full bg-primary/30" />
      </div>
      <div>
        <p className="text-[15px] font-semibold leading-6 text-foreground">{title}</p>
        <p className="mt-1 max-w-sm text-[13px] leading-5">{description}</p>
      </div>
    </div>
  )
}

export function IndexPage() {
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingProgress, setLoadingProgress] = useState(0)
  const [timeRange, setTimeRange] = useState(24) // 默认24小时
  const [timeRangeDialogOpen, setTimeRangeDialogOpen] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null)
  const [restarting, setRestarting] = useState(false)
  const { toast } = useToast()

  // 获取机器人状态
  const fetchBotStatus = useCallback(async () => {
    try {
      const response = await axios.get('/api/webui/system/status', {
        withCredentials: true,
      })
      setBotStatus(response.data)
    } catch (error) {
      console.error('获取机器人状态失败:', error)
      setBotStatus(null)
    }
  }, [])

  // 重启机器人
  const handleRestart = async () => {
    if (restarting) return

    try {
      setRestarting(true)
      await axios.post(
        '/api/webui/system/restart',
        {},
        {
          withCredentials: true,
        }
      )
      toast({
        title: '重启中',
        description: '主程序正在重启，请稍候...',
      })
      // 3秒后刷新状态
      setTimeout(() => {
        fetchBotStatus()
        setRestarting(false)
      }, 3000)
    } catch (error) {
      console.error('重启失败:', error)
      toast({
        title: '重启失败',
        description: '无法重启主程序，请检查控制台',
        variant: 'destructive',
      })
      setRestarting(false)
    }
  }

  const fetchDashboardData = useCallback(async () => {
    try {
      const response = await axios.get(`/api/webui/statistics/dashboard?hours=${timeRange}`, {
        withCredentials: true,
      })
      setDashboardData(response.data)
      setLoading(false)
      setLoadingProgress(100)
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error)
      setLoading(false)
      setLoadingProgress(100)
    }
  }, [timeRange])

  // 伪加载进度条效果
  useEffect(() => {
    if (!loading) return

    setLoadingProgress(0)

    // 快速到15%
    const timer1 = setTimeout(() => setLoadingProgress(15), 200)
    // 到30%
    const timer2 = setTimeout(() => setLoadingProgress(30), 800)
    // 到45%
    const timer3 = setTimeout(() => setLoadingProgress(45), 2000)
    // 到60%
    const timer4 = setTimeout(() => setLoadingProgress(60), 4000)
    // 到75%
    const timer5 = setTimeout(() => setLoadingProgress(75), 6500)
    // 到85%
    const timer6 = setTimeout(() => setLoadingProgress(85), 9000)
    // 到92%
    const timer7 = setTimeout(() => setLoadingProgress(92), 11000)

    return () => {
      clearTimeout(timer1)
      clearTimeout(timer2)
      clearTimeout(timer3)
      clearTimeout(timer4)
      clearTimeout(timer5)
      clearTimeout(timer6)
      clearTimeout(timer7)
    }
  }, [loading])

  useEffect(() => {
    fetchDashboardData()
    fetchBotStatus()
  }, [fetchDashboardData, fetchBotStatus])

  // 自动刷新
  useEffect(() => {
    if (!autoRefresh) return

    const interval = setInterval(() => {
      fetchDashboardData()
      fetchBotStatus()
    }, 30000) // 30秒刷新一次

    return () => clearInterval(interval)
  }, [autoRefresh, fetchDashboardData, fetchBotStatus])

  if (loading || !dashboardData) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <div className="ios-card w-full max-w-md space-y-6 px-5 py-6 text-center">
          <RefreshCw className="ios-spin-slow mx-auto h-12 w-12 text-primary" />
          <div className="space-y-2">
            <p className="text-lg font-medium">加载统计数据中...</p>
            <p className="text-sm text-muted-foreground">正在获取运行数据</p>
          </div>
          <div className="space-y-2">
            <Progress value={loadingProgress} className="h-2" />
            <p className="text-xs text-muted-foreground">{loadingProgress}%</p>
          </div>
        </div>
      </div>
    )
  }

  // 解构数据，提供默认值以防止 undefined 错误
  const {
    summary: rawSummary,
    model_stats = [],
    hourly_data = [],
    daily_data = [],
    recent_activity = [],
  } = dashboardData

  // 为 summary 提供默认值
  const summary = rawSummary ?? {
    total_requests: 0,
    total_cost: 0,
    total_tokens: 0,
    online_time: 0,
    total_messages: 0,
    total_replies: 0,
    avg_response_time: 0,
    cost_per_hour: 0,
    tokens_per_hour: 0,
  }

  // 格式化时间显示
  const formatTime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    if (hours > 0 && minutes > 0) return `${hours} 小时 ${minutes} 分钟`
    if (hours > 0) return `${hours} 小时`
    if (minutes > 0) return `${minutes} 分钟`
    return '刚刚'
  }

  // 格式化大数字（自动选择合适单位）
  const formatNumber = (num: number): { display: string; exact: string; needsExact: boolean } => {
    const exact = num.toLocaleString('zh-CN')

    if (num >= 1_000_000_000) {
      return { display: `${(num / 1_000_000_000).toFixed(2)}B`, exact, needsExact: true }
    } else if (num >= 1_000_000) {
      return { display: `${(num / 1_000_000).toFixed(2)}M`, exact, needsExact: true }
    } else if (num >= 10_000) {
      return { display: `${(num / 1_000).toFixed(1)}K`, exact, needsExact: true }
    } else if (num >= 1_000) {
      return { display: `${(num / 1_000).toFixed(2)}K`, exact, needsExact: true }
    }
    return { display: exact, exact, needsExact: false }
  }

  // 格式化金额（自动选择合适单位）
  const formatCurrency = (num: number): { display: string; exact: string; needsExact: boolean } => {
    const exact = `¥${num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

    if (num >= 1_000_000) {
      return { display: `¥${(num / 1_000_000).toFixed(2)}M`, exact, needsExact: true }
    } else if (num >= 10_000) {
      return { display: `¥${(num / 1_000).toFixed(1)}K`, exact, needsExact: true }
    } else if (num >= 1_000) {
      return { display: `¥${(num / 1_000).toFixed(2)}K`, exact, needsExact: true }
    }
    return { display: exact, exact, needsExact: false }
  }

  // 格式化日期时间
  const formatDateTime = (isoString: string) => {
    const date = new Date(isoString)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // 准备饼图数据（模型请求分布）- 使用黄金角度分布避免相邻颜色相似
  const pieColors = generatePieColors(model_stats.length)
  const modelPieData = model_stats.map((stat, index) => ({
    name: stat.model_name,
    value: stat.request_count,
    fill: pieColors[index],
  }))

  // 图表配置
  const chartConfig = {
    requests: {
      label: '请求数',
      color: 'hsl(var(--chart-1))',
    },
    cost: {
      label: '花费(¥)',
      color: 'hsl(var(--chart-2))',
    },
    tokens: {
      label: 'Tokens',
      color: 'hsl(var(--chart-3))',
    },
  } satisfies ChartConfig

  const timeRangeLabel =
    timeRangeOptions.find((option) => option.value === timeRange)?.label ?? `${timeRange}小时`
  const visibleRangeLabel = timeRange < 48 ? `${timeRange}小时` : `${Math.floor(timeRange / 24)}天`
  const totalRequests = formatNumber(summary.total_requests)
  const totalCost = formatCurrency(summary.total_cost)
  const totalTokens = formatNumber(summary.total_tokens)
  const totalMessages = formatNumber(summary.total_messages)
  const totalReplies = formatNumber(summary.total_replies)
  const costEfficiency =
    summary.total_messages > 0
      ? `¥${((summary.total_cost / summary.total_messages) * 100).toFixed(2)}`
      : '¥0.00'
  const coreMetricRows = [
    {
      title: '总请求数',
      value: totalRequests.display,
      exact: totalRequests.needsExact ? totalRequests.exact : undefined,
      detail: `最近${visibleRangeLabel}`,
      icon: Activity,
      iconClassName: 'ios-symbol-blue',
    },
    {
      title: '总花费',
      value: totalCost.display,
      exact: totalCost.needsExact ? totalCost.exact : undefined,
      detail: summary.cost_per_hour > 0 ? `¥${summary.cost_per_hour.toFixed(2)}/小时` : '暂无数据',
      icon: DollarSign,
      iconClassName: 'ios-symbol-green',
    },
    {
      title: 'Token 消耗',
      value: totalTokens.display,
      exact: totalTokens.needsExact ? totalTokens.exact : undefined,
      detail:
        summary.tokens_per_hour > 0
          ? `${formatNumber(summary.tokens_per_hour).display}/小时`
          : '暂无数据',
      icon: Database,
      iconClassName: 'ios-symbol-purple',
    },
    {
      title: '平均响应',
      value: `${summary.avg_response_time.toFixed(2)}s`,
      exact: undefined,
      detail: 'API 平均耗时',
      icon: Zap,
      iconClassName: 'ios-symbol-orange',
    },
  ]
  const secondaryMetricRows = [
    {
      title: '在线时长',
      value: formatTime(summary.online_time),
      exact: `${summary.online_time.toLocaleString()} 秒`,
      detail: '运行累计',
      icon: Clock,
      iconClassName: 'ios-symbol-teal',
    },
    {
      title: '消息处理',
      value: totalMessages.display,
      exact: totalMessages.needsExact ? totalMessages.exact : undefined,
      detail: `回复 ${totalReplies.display} 条`,
      icon: MessageSquare,
      iconClassName: 'ios-symbol-purple',
    },
    {
      title: '成本效率',
      value: costEfficiency,
      exact: undefined,
      detail: '每 100 条消息',
      icon: TrendingUp,
      iconClassName: 'ios-symbol-pink',
    },
  ]

  return (
    <ScrollArea className="h-full">
      <div className="ios-page">
        <div className="mx-auto w-full max-w-6xl space-y-8 sm:space-y-9 lg:space-y-10">
          {/* 标题和控制栏 */}
          <div className="flex flex-col justify-between gap-5 sm:gap-6 lg:flex-row lg:items-center">
            <div className="min-w-0">
              <h1 className="ios-title">实时监控面板</h1>
              <p className="ios-subtitle">主程序运行状态和统计数据一览</p>
            </div>
            <div className="hidden w-full flex-col gap-3 sm:flex sm:w-auto sm:flex-row sm:items-center">
              <Tabs
                value={timeRange.toString()}
                onValueChange={(v) => setTimeRange(Number(v))}
                className="w-full sm:w-auto"
              >
                <TabsList className="grid w-full grid-cols-3 sm:w-auto">
                  <TabsTrigger value="24">24小时</TabsTrigger>
                  <TabsTrigger value="168">7天</TabsTrigger>
                  <TabsTrigger value="720">30天</TabsTrigger>
                </TabsList>
              </Tabs>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:flex sm:items-center">
                <div className="ios-group flex min-h-11 min-w-0 items-center justify-between gap-4 px-4 sm:min-w-[190px]">
                  <div className="flex min-w-0 items-center gap-2">
                    <RefreshCw className="h-4 w-4 shrink-0 text-primary" />
                    <span className="truncate text-sm font-medium">自动刷新</span>
                  </div>
                  <Switch
                    checked={autoRefresh}
                    onCheckedChange={setAutoRefresh}
                    aria-label="自动刷新"
                  />
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  className="h-11 w-11 rounded-full"
                  onClick={fetchDashboardData}
                  aria-label="手动刷新"
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>

          <div className="ios-group overflow-hidden sm:hidden">
            <Dialog open={timeRangeDialogOpen} onOpenChange={setTimeRangeDialogOpen}>
              <DialogTrigger asChild>
                <button className="ios-row ios-touch min-h-[66px] w-full gap-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                      <Clock className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[16px] font-medium leading-6">首页数据</span>
                      <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                        {timeRangeLabel} · {autoRefresh ? '自动刷新' : '手动刷新'}
                      </span>
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="inline-flex h-9 items-center rounded-full bg-secondary/80 px-3 text-[14px] font-semibold leading-none text-foreground">
                      {timeRangeLabel}
                    </span>
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </span>
                </button>
              </DialogTrigger>
              <DialogContent className="ios-sheet bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
                <DialogHeader className="px-5 pt-7">
                  <DialogTitle>统计范围</DialogTitle>
                  <DialogDescription>选择首页统计数据的时间窗口</DialogDescription>
                </DialogHeader>
                <div className="px-5">
                  <div className="ios-group overflow-hidden">
                    {timeRangeOptions.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                        onClick={() => {
                          setTimeRange(option.value)
                          setTimeRangeDialogOpen(false)
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
                        {timeRange === option.value ? (
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

            <div className="ios-row min-h-[58px] py-2.5">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                  <RefreshCw className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[15px] font-medium leading-5">自动刷新</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    每 30 秒更新一次状态
                  </span>
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <Switch
                  checked={autoRefresh}
                  onCheckedChange={setAutoRefresh}
                  aria-label="自动刷新"
                />
                <button
                  type="button"
                  onClick={fetchDashboardData}
                  className="ios-touch inline-flex h-11 w-11 items-center justify-center rounded-full bg-secondary/85 text-foreground hover:bg-secondary focus-visible:bg-accent/70 focus-visible:ring-0"
                  aria-label="立即刷新"
                >
                  <RefreshCw className="h-4 w-4" />
                </button>
              </span>
            </div>
          </div>

          {/* 移动端概览分组 */}
          <div className="space-y-4 sm:hidden">
            <div className="ios-group overflow-hidden">
              <div className="ios-row min-h-[68px]">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                    <Power className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-[15px] font-medium leading-tight">主程序</p>
                    <p className="mt-1 text-[13px] leading-tight text-muted-foreground">
                      {botStatus?.running ? '正在运行' : '已停止'}
                    </p>
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className={
                    botStatus?.running
                      ? 'border-[rgb(52_199_89_/_0.24)] bg-[rgb(52_199_89_/_0.1)] px-3 py-1 text-[13px] font-semibold text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
                      : 'border-[rgb(255_59_48_/_0.22)] bg-[rgb(255_59_48_/_0.1)] px-3 py-1 text-[13px] font-semibold text-[rgb(215_0_21)] dark:text-[rgb(255_69_58)]'
                  }
                >
                  {botStatus?.running ? '运行中' : '已停止'}
                </Badge>
              </div>
              {botStatus && (
                <>
                  <div className="ios-row min-h-12 py-3">
                    <span className="text-[15px] text-muted-foreground">版本</span>
                    <span className="text-[15px] font-medium">v{botStatus.version}</span>
                  </div>
                  <div className="ios-row min-h-12 py-3">
                    <span className="text-[15px] text-muted-foreground">运行时长</span>
                    <span className="text-[15px] font-medium">{formatTime(botStatus.uptime)}</span>
                  </div>
                </>
              )}
            </div>

            <div className="space-y-2">
              <div className="px-1">
                <h2 className="text-[13px] font-medium leading-5 text-muted-foreground">
                  核心指标
                </h2>
              </div>
              <div className="ios-group overflow-hidden">
                {coreMetricRows.map(({ title, value, detail, icon: Icon, iconClassName }) => (
                  <div key={title} className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 flex-1 items-center gap-3">
                      <span className={`ios-symbol ios-symbol-sm ${iconClassName}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-[15px] font-medium leading-5">
                          {title}
                        </span>
                        <span className="mt-1 block truncate text-[13px] leading-5 text-muted-foreground">
                          {detail}
                        </span>
                      </span>
                    </span>
                    <span className="max-w-[45%] truncate text-right text-[17px] font-semibold tabular-nums leading-6">
                      {value}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="ios-group overflow-hidden">
              {secondaryMetricRows.map(({ title, value, detail, icon: Icon, iconClassName }) => (
                <div key={title} className="ios-row min-h-[62px]">
                  <span className="flex min-w-0 flex-1 items-center gap-3">
                    <span className={`ios-symbol ios-symbol-sm ${iconClassName}`}>
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[15px] font-medium leading-5">
                        {title}
                      </span>
                      <span className="mt-1 block truncate text-[13px] leading-5 text-muted-foreground">
                        {detail}
                      </span>
                    </span>
                  </span>
                  <span className="max-w-[45%] truncate text-right text-[16px] font-semibold tabular-nums leading-6">
                    {value}
                  </span>
                </div>
              ))}
            </div>

            <div className="ios-group overflow-hidden">
              <button
                type="button"
                onClick={handleRestart}
                disabled={restarting}
                className="ios-row ios-touch w-full text-left disabled:opacity-60 disabled:active:scale-100"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                    <RotateCcw className={`h-4 w-4 ${restarting ? 'ios-spin-slow' : ''}`} />
                  </span>
                  <span className="text-[15px] font-medium">
                    {restarting ? '重启中...' : '重启主程序'}
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </button>
              <Link to="/logs" className="ios-row ios-touch">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-teal">
                    <FileText className="h-4 w-4" />
                  </span>
                  <span className="text-[15px] font-medium">查看日志</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </Link>
              <Link to="/plugins" className="ios-row ios-touch">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                    <Puzzle className="h-4 w-4" />
                  </span>
                  <span className="text-[15px] font-medium">插件管理</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </Link>
              <Link to="/settings" className="ios-row ios-touch">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                    <Settings className="h-4 w-4" />
                  </span>
                  <span className="text-[15px] font-medium">系统设置</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </Link>
            </div>
          </div>

          {/* 机器人状态和快捷入口 */}
          <div className="hidden grid-cols-1 gap-5 sm:grid lg:grid-cols-2 lg:gap-6">
            <div className="ios-group overflow-hidden">
              <div className="ios-row min-h-[76px]">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-md ios-symbol-green">
                    <Power className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-semibold leading-5">主程序状态</span>
                    <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">
                      {botStatus?.running ? '正在运行' : '已停止'}
                    </span>
                  </span>
                </span>
                <Badge
                  variant="outline"
                  className={
                    botStatus?.running
                      ? 'border-[rgb(52_199_89_/_0.24)] bg-[rgb(52_199_89_/_0.1)] px-3 py-1 text-[13px] font-semibold text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
                      : 'border-[rgb(255_59_48_/_0.22)] bg-[rgb(255_59_48_/_0.1)] px-3 py-1 text-[13px] font-semibold text-[rgb(215_0_21)] dark:text-[rgb(255_69_58)]'
                  }
                >
                  {botStatus?.running ? '运行中' : '已停止'}
                </Badge>
              </div>
              {botStatus && (
                <>
                  <div className="ios-row min-h-12 py-3">
                    <span className="text-[15px] text-muted-foreground">版本</span>
                    <span className="max-w-[55%] truncate text-right text-[15px] font-medium">
                      v{botStatus.version}
                    </span>
                  </div>
                  <div className="ios-row min-h-12 py-3">
                    <span className="text-[15px] text-muted-foreground">运行时长</span>
                    <span className="max-w-[55%] truncate text-right text-[15px] font-medium">
                      {formatTime(botStatus.uptime)}
                    </span>
                  </div>
                </>
              )}
            </div>

            <div className="ios-group overflow-hidden">
              <button
                type="button"
                onClick={handleRestart}
                disabled={restarting}
                className="ios-row ios-touch w-full text-left disabled:opacity-60 disabled:active:scale-100"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-md ios-symbol-blue">
                    <RotateCcw className={`h-4 w-4 ${restarting ? 'ios-spin-slow' : ''}`} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-semibold leading-5">
                      {restarting ? '重启中...' : '重启主程序'}
                    </span>
                    <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">
                      重新加载运行进程
                    </span>
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </button>
              <Link to="/logs" className="ios-row ios-touch">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-md ios-symbol-teal">
                    <FileText className="h-4 w-4" />
                  </span>
                  <span className="text-[15px] font-semibold leading-5">查看日志</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </Link>
              <Link to="/plugins" className="ios-row ios-touch">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-md ios-symbol-purple">
                    <Puzzle className="h-4 w-4" />
                  </span>
                  <span className="text-[15px] font-semibold leading-5">插件管理</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </Link>
              <Link to="/settings" className="ios-row ios-touch">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-md ios-symbol-gray">
                    <Settings className="h-4 w-4" />
                  </span>
                  <span className="text-[15px] font-semibold leading-5">系统设置</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </Link>
            </div>
          </div>

          {/* 核心指标 */}
          <div className="hidden gap-5 sm:grid sm:grid-cols-2 lg:grid-cols-4">
            {coreMetricRows.map(({ title, value, exact, detail, icon: Icon, iconClassName }) => (
              <div key={title} className="ios-metric-card min-h-[152px] sm:p-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                      {title}
                    </p>
                    <p className="mt-1 truncate text-[12px] leading-5 text-muted-foreground/80">
                      {detail}
                    </p>
                  </div>
                  <span className={`ios-symbol ios-symbol-md ${iconClassName}`}>
                    <Icon className="h-4 w-4" />
                  </span>
                </div>
                <div className="mt-7 min-w-0">
                  <p className="truncate text-[32px] font-semibold tabular-nums leading-none tracking-normal">
                    {value}
                  </p>
                  {exact && (
                    <p className="mt-2 truncate text-[12px] leading-5 text-muted-foreground">
                      精确值 {exact}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* 次要指标 */}
          <div className="hidden grid-cols-1 gap-5 sm:grid sm:grid-cols-3">
            {secondaryMetricRows.map(({ title, value, detail, icon: Icon, iconClassName }) => (
              <div key={title} className="ios-metric-card min-h-[128px] sm:p-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                      {title}
                    </p>
                    <p className="mt-1 truncate text-[12px] leading-5 text-muted-foreground/80">
                      {detail}
                    </p>
                  </div>
                  <span className={`ios-symbol ios-symbol-md ${iconClassName}`}>
                    <Icon className="h-4 w-4" />
                  </span>
                </div>
                <p className="mt-6 truncate text-[26px] font-semibold tabular-nums leading-none tracking-normal">
                  {value}
                </p>
              </div>
            ))}
          </div>

          {/* 图表区域 */}
          <Tabs defaultValue="trends" className="space-y-5 sm:space-y-6">
            <TabsList className="grid w-full grid-cols-2 sm:grid-cols-4">
              <TabsTrigger value="trends">趋势</TabsTrigger>
              <TabsTrigger value="models">模型</TabsTrigger>
              <TabsTrigger value="activity">活动</TabsTrigger>
              <TabsTrigger value="daily">日统计</TabsTrigger>
            </TabsList>

            {/* 趋势图表 */}
            <TabsContent value="trends" className="space-y-5 sm:space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>请求趋势</CardTitle>
                  <CardDescription>最近{timeRange}小时的请求量变化</CardDescription>
                </CardHeader>
                <CardContent>
                  {hourly_data.length > 0 ? (
                    <ChartContainer
                      config={chartConfig}
                      className="aspect-auto h-[300px] w-full sm:h-[400px]"
                    >
                      <LineChart data={hourly_data}>
                        <CartesianGrid vertical={false} stroke={chartGridStroke} />
                        <XAxis
                          dataKey="timestamp"
                          tickFormatter={(value) => formatDateTime(value)}
                          angle={-45}
                          textAnchor="end"
                          height={60}
                          stroke={chartAxisStroke}
                          tick={chartAxisTick}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          stroke={chartAxisStroke}
                          tick={chartAxisTick}
                          tickLine={false}
                          axisLine={false}
                        />
                        <ChartTooltip
                          content={
                            <ChartTooltipContent
                              labelFormatter={(value) => formatDateTime(value as string)}
                            />
                          }
                        />
                        <Line
                          type="monotone"
                          dataKey="requests"
                          stroke="var(--color-requests)"
                          strokeWidth={2.5}
                        />
                      </LineChart>
                    </ChartContainer>
                  ) : (
                    <ChartEmptyState />
                  )}
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 lg:gap-6">
                <Card>
                  <CardHeader>
                    <CardTitle>花费趋势</CardTitle>
                    <CardDescription>API调用成本变化</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {hourly_data.length > 0 ? (
                      <ChartContainer
                        config={chartConfig}
                        className="aspect-auto h-[250px] w-full sm:h-[300px]"
                      >
                        <BarChart data={hourly_data}>
                          <CartesianGrid vertical={false} stroke={chartGridStroke} />
                          <XAxis
                            dataKey="timestamp"
                            tickFormatter={(value) => formatDateTime(value)}
                            angle={-45}
                            textAnchor="end"
                            height={60}
                            stroke={chartAxisStroke}
                            tick={chartAxisTick}
                            tickLine={false}
                            axisLine={false}
                          />
                          <YAxis
                            stroke={chartAxisStroke}
                            tick={chartAxisTick}
                            tickLine={false}
                            axisLine={false}
                          />
                          <ChartTooltip
                            content={
                              <ChartTooltipContent
                                labelFormatter={(value) => formatDateTime(value as string)}
                              />
                            }
                          />
                          <Bar dataKey="cost" fill="var(--color-cost)" radius={[6, 6, 0, 0]} />
                        </BarChart>
                      </ChartContainer>
                    ) : (
                      <ChartEmptyState description="产生 API 调用成本后这里会显示变化趋势" />
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Token消耗</CardTitle>
                    <CardDescription>Token使用量变化</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {hourly_data.length > 0 ? (
                      <ChartContainer
                        config={chartConfig}
                        className="aspect-auto h-[250px] w-full sm:h-[300px]"
                      >
                        <BarChart data={hourly_data}>
                          <CartesianGrid vertical={false} stroke={chartGridStroke} />
                          <XAxis
                            dataKey="timestamp"
                            tickFormatter={(value) => formatDateTime(value)}
                            angle={-45}
                            textAnchor="end"
                            height={60}
                            stroke={chartAxisStroke}
                            tick={chartAxisTick}
                            tickLine={false}
                            axisLine={false}
                          />
                          <YAxis
                            stroke={chartAxisStroke}
                            tick={chartAxisTick}
                            tickLine={false}
                            axisLine={false}
                          />
                          <ChartTooltip
                            content={
                              <ChartTooltipContent
                                labelFormatter={(value) => formatDateTime(value as string)}
                              />
                            }
                          />
                          <Bar dataKey="tokens" fill="var(--color-tokens)" radius={[6, 6, 0, 0]} />
                        </BarChart>
                      </ChartContainer>
                    ) : (
                      <ChartEmptyState description="产生 Token 消耗后这里会显示变化趋势" />
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            {/* 模型统计 */}
            <TabsContent value="models" className="space-y-4">
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 lg:gap-6">
                <Card>
                  <CardHeader>
                    <CardTitle>模型请求分布</CardTitle>
                    <CardDescription>
                      各模型使用占比 (共 {model_stats.length} 个模型)
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {modelPieData.length > 0 ? (
                      <div>
                        <ChartContainer
                          config={
                            Object.fromEntries(
                              model_stats.map((stat, i) => [
                                stat.model_name,
                                {
                                  label: stat.model_name,
                                  color: pieColors[i],
                                },
                              ])
                            ) as ChartConfig
                          }
                          className="aspect-auto h-[240px] w-full sm:h-[400px] [&_.recharts-pie-label-text]:hidden sm:[&_.recharts-pie-label-text]:block"
                        >
                          <PieChart>
                            <ChartTooltip content={<ChartTooltipContent />} />
                            <Pie
                              data={modelPieData}
                              cx="50%"
                              cy="50%"
                              labelLine={false}
                              label={({ name, percent }) => {
                                // 只显示占比大于5%的标签，避免小块标签重叠
                                if (percent && percent < 0.05) return ''
                                return `${name} ${percent ? (percent * 100).toFixed(0) : 0}%`
                              }}
                              outerRadius={100}
                              dataKey="value"
                            >
                              {modelPieData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.fill} />
                              ))}
                            </Pie>
                          </PieChart>
                        </ChartContainer>
                        <ModelPieLegend data={modelPieData} />
                      </div>
                    ) : (
                      <ChartEmptyState
                        title="暂无模型统计"
                        description="模型产生请求后这里会显示使用占比"
                      />
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>模型详细统计</CardTitle>
                    <CardDescription>请求数、花费和性能</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {model_stats.length > 0 ? (
                      <ScrollArea className="h-[300px] sm:h-[400px]">
                        <div className="ios-group overflow-hidden">
                          {model_stats.map((stat, index) => (
                            <div key={index} className="ios-row min-h-[86px]">
                              <span className="flex min-w-0 flex-1 items-center gap-3">
                                <span
                                  className="h-3 w-3 shrink-0 rounded-full"
                                  style={{ backgroundColor: pieColors[index] }}
                                />
                                <span className="min-w-0">
                                  <span className="block truncate text-[15px] font-semibold leading-5">
                                    {stat.model_name}
                                  </span>
                                  <span className="mt-1 block truncate text-[13px] leading-5 text-muted-foreground">
                                    {stat.request_count.toLocaleString()} 次 · ¥
                                    {stat.total_cost.toFixed(2)} ·{' '}
                                    {(stat.total_tokens / 1000).toFixed(1)}K Tokens
                                  </span>
                                </span>
                              </span>
                              <span className="shrink-0 text-right text-[13px] leading-5 text-muted-foreground">
                                {stat.avg_response_time.toFixed(2)}s
                              </span>
                            </div>
                          ))}
                        </div>
                      </ScrollArea>
                    ) : (
                      <ChartEmptyState
                        title="暂无模型明细"
                        description="模型调用完成后这里会显示请求、成本和性能"
                      />
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
            <TabsContent value="activity">
              <Card>
                <CardHeader>
                  <CardTitle>最近活动</CardTitle>
                  <CardDescription>最新的API调用记录</CardDescription>
                </CardHeader>
                <CardContent>
                  {recent_activity.length > 0 ? (
                    <ScrollArea className="h-[400px] sm:h-[500px]">
                      <div className="ios-group overflow-hidden">
                        {recent_activity.map((activity, index) => (
                          <div key={index} className="ios-row min-h-[92px]">
                            <span className="flex min-w-0 flex-1 items-center gap-3">
                              <span
                                className={`ios-symbol ios-symbol-md ${
                                  activity.status === 'success'
                                    ? 'ios-symbol-green'
                                    : 'ios-symbol-red'
                                }`}
                              >
                                <Activity className="h-4 w-4" />
                              </span>
                              <span className="min-w-0">
                                <span className="block truncate text-[15px] font-semibold leading-5">
                                  {activity.model}
                                </span>
                                <span className="mt-1 block truncate text-[13px] leading-5 text-muted-foreground">
                                  {activity.request_type} · {activity.tokens} Tokens · ¥
                                  {activity.cost.toFixed(4)}
                                </span>
                              </span>
                            </span>
                            <span className="shrink-0 text-right text-[13px] leading-5 text-muted-foreground">
                              <span className="block">{formatDateTime(activity.timestamp)}</span>
                              <span className="block">{activity.time_cost.toFixed(2)}s</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  ) : (
                    <ChartEmptyState
                      title="暂无最近活动"
                      description="新的 API 调用记录会显示在这里"
                    />
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* 日统计 */}
            <TabsContent value="daily">
              <Card>
                <CardHeader>
                  <CardTitle>每日统计</CardTitle>
                  <CardDescription>最近7天的数据汇总</CardDescription>
                </CardHeader>
                <CardContent>
                  {daily_data.length > 0 ? (
                    <ChartContainer
                      config={{
                        requests: {
                          label: '请求数',
                          color: 'hsl(var(--chart-1))',
                        },
                        cost: {
                          label: '花费(¥)',
                          color: 'hsl(var(--chart-2))',
                        },
                      }}
                      className="aspect-auto h-[400px] w-full sm:h-[500px]"
                    >
                      <BarChart data={daily_data}>
                        <CartesianGrid vertical={false} stroke={chartGridStroke} />
                        <XAxis
                          dataKey="timestamp"
                          tickFormatter={(value) => {
                            const date = new Date(value)
                            return `${date.getMonth() + 1}/${date.getDate()}`
                          }}
                          stroke={chartAxisStroke}
                          tick={chartAxisTick}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          yAxisId="left"
                          stroke={chartAxisStroke}
                          tick={chartAxisTick}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          yAxisId="right"
                          orientation="right"
                          stroke={chartAxisStroke}
                          tick={chartAxisTick}
                          tickLine={false}
                          axisLine={false}
                        />
                        <ChartTooltip
                          content={
                            <ChartTooltipContent
                              labelFormatter={(value) => {
                                const date = new Date(value as string)
                                return date.toLocaleDateString('zh-CN')
                              }}
                            />
                          }
                        />
                        <ChartLegend content={<ChartLegendContent />} />
                        <Bar
                          yAxisId="left"
                          dataKey="requests"
                          fill="var(--color-requests)"
                          radius={[6, 6, 0, 0]}
                        />
                        <Bar
                          yAxisId="right"
                          dataKey="cost"
                          fill="var(--color-cost)"
                          radius={[6, 6, 0, 0]}
                        />
                      </BarChart>
                    </ChartContainer>
                  ) : (
                    <ChartEmptyState
                      title="暂无每日统计"
                      description="累积到按天汇总的数据后这里会显示对比"
                    />
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </ScrollArea>
  )
}
