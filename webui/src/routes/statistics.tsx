import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, BarChart3, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { BreakdownTable, type BreakdownRow } from '@/components/statistics/breakdown-table'
import { ChatTable } from '@/components/statistics/chat-table'
import { formatDateTime } from '@/components/statistics/format'
import { RecentActivity } from '@/components/statistics/recent-activity'
import { SummaryGrid } from '@/components/statistics/summary-grid'
import { TrendChart } from '@/components/statistics/trend-chart'
import { useToast } from '@/hooks/use-toast'
import { fetchStatisticsReport } from '@/lib/statistics-api'
import type { StatisticsReport } from '@/types/statistics'

const timeRanges = [
  { hours: 24, label: '24 小时' },
  { hours: 168, label: '7 天' },
  { hours: 720, label: '30 天' },
  { hours: 2160, label: '90 天' },
]

function StatisticsSkeleton() {
  return (
    <div className="space-y-5 sm:space-y-7" aria-busy="true" aria-label="加载统计数据">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        {Array.from({ length: 8 }).map((_, index) => (
          <div key={index} className="ios-stat-card space-y-4">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-8 w-28" />
            <Skeleton className="h-3 w-24" />
          </div>
        ))}
      </div>
      <div className="ios-card space-y-5 p-5 sm:p-6">
        <Skeleton className="h-6 w-28" />
        <Skeleton className="h-[280px] w-full" />
      </div>
      <div className="ios-card space-y-5 p-5 sm:p-6">
        <Skeleton className="h-11 w-full max-w-md" />
        <Skeleton className="h-[300px] w-full" />
      </div>
    </div>
  )
}

function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="ios-card flex min-h-[300px] flex-col items-center justify-center gap-4 px-6 text-center">
      <span className="ios-symbol ios-symbol-md ios-symbol-red" aria-hidden="true">
        <AlertCircle className="h-5 w-5" />
      </span>
      <div>
        <p className="text-[17px] font-semibold text-foreground">统计数据加载失败</p>
        <p className="mt-1 max-w-md text-sm leading-6 text-muted-foreground">{message}</p>
      </div>
      <Button variant="outline" onClick={onRetry}>
        <RefreshCw className="mr-2 h-4 w-4" />
        重试
      </Button>
    </div>
  )
}

export function StatisticsPage() {
  const [hours, setHours] = useState(24)
  const [report, setReport] = useState<StatisticsReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { toast } = useToast()

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setReport(null)

    fetchStatisticsReport(hours, controller.signal)
      .then(setReport)
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setError(caught instanceof Error ? caught.message : '无法获取统计数据')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [hours])

  const refresh = useCallback(async () => {
    try {
      setRefreshing(true)
      setError(null)
      setReport(await fetchStatisticsReport(hours))
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '无法获取统计数据'
      setError(message)
      toast({ title: '刷新失败', description: message, variant: 'destructive' })
    } finally {
      setRefreshing(false)
      setLoading(false)
    }
  }, [hours, toast])

  const modelRows: BreakdownRow[] =
    report?.model_stats.map((row) => ({ ...row, name: row.model_name })) ?? []
  const rangeLabel = timeRanges.find((item) => item.hours === hours)?.label ?? `${hours} 小时`

  return (
    <div className="ios-page h-full overflow-y-auto">
      <div className="ios-content">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <span className="ios-symbol ios-symbol-md ios-symbol-blue" aria-hidden="true">
                <BarChart3 className="h-5 w-5" />
              </span>
              <h1 className="ios-title">统计数据</h1>
            </div>
            <p className="ios-subtitle">
              {report
                ? `${formatDateTime(report.period.start_time)} 至 ${formatDateTime(report.period.end_time)}`
                : rangeLabel}
            </p>
          </div>

          <div className="flex max-w-full items-center gap-2 overflow-x-auto pb-1 sm:justify-end">
            <Tabs value={String(hours)} onValueChange={(value) => setHours(Number(value))}>
              <TabsList className="min-h-11 shrink-0">
                {timeRanges.map((range) => (
                  <TabsTrigger
                    key={range.hours}
                    value={String(range.hours)}
                    className="min-h-9 px-3"
                    disabled={refreshing || loading}
                  >
                    {range.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="h-11 w-11 shrink-0 rounded-[14px]"
                  onClick={refresh}
                  disabled={refreshing || loading}
                  aria-label="刷新统计数据"
                >
                  <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>刷新统计数据</TooltipContent>
            </Tooltip>
          </div>
        </header>

        {loading && !report ? (
          <StatisticsSkeleton />
        ) : error && !report ? (
          <LoadError message={error} onRetry={refresh} />
        ) : report ? (
          <>
            <SummaryGrid summary={report.summary} />

            <section className="ios-card p-5 sm:p-6" aria-labelledby="statistics-trend-title">
              <div className="mb-1">
                <h2 id="statistics-trend-title" className="text-[19px] font-semibold leading-7">
                  使用趋势
                </h2>
                <p className="text-[13px] leading-5 text-muted-foreground">
                  {report.time_series_granularity === 'hour' ? '按小时汇总' : '按天汇总'}
                </p>
              </div>
              <TrendChart data={report.time_series} granularity={report.time_series_granularity} />
            </section>

            <section className="ios-card p-5 sm:p-6" aria-labelledby="statistics-breakdown-title">
              <h2
                id="statistics-breakdown-title"
                className="mb-4 text-[19px] font-semibold leading-7"
              >
                分类明细
              </h2>
              <Tabs defaultValue="models">
                <TabsList className="mb-4 max-w-full justify-start overflow-x-auto">
                  <TabsTrigger value="models">模型</TabsTrigger>
                  <TabsTrigger value="modules">模块</TabsTrigger>
                  <TabsTrigger value="request-types">请求类型</TabsTrigger>
                  <TabsTrigger value="chats">聊天</TabsTrigger>
                </TabsList>
                <TabsContent value="models">
                  <BreakdownTable rows={modelRows} nameLabel="模型" />
                </TabsContent>
                <TabsContent value="modules">
                  <BreakdownTable rows={report.module_stats} nameLabel="模块" />
                </TabsContent>
                <TabsContent value="request-types">
                  <BreakdownTable rows={report.request_type_stats} nameLabel="请求类型" />
                </TabsContent>
                <TabsContent value="chats">
                  <ChatTable rows={report.chat_stats} />
                </TabsContent>
              </Tabs>
            </section>

            <section className="ios-card p-5 sm:p-6" aria-labelledby="statistics-activity-title">
              <div className="mb-4">
                <h2 id="statistics-activity-title" className="text-[19px] font-semibold leading-7">
                  最近请求
                </h2>
                <p className="text-[13px] leading-5 text-muted-foreground">
                  显示最近 30 条数据库记录
                </p>
              </div>
              <RecentActivity rows={report.recent_activity} />
            </section>
          </>
        ) : null}
      </div>
    </div>
  )
}
