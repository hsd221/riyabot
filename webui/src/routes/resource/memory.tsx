import { Fragment, useCallback, useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import {
  Brain,
  RefreshCw,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Database,
  Sparkles,
  Zap,
  Filter,
  BarChart3,
  Lightbulb,
  VolumeX,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Cell } from 'recharts'
import type { MemoryStats, AtomData, DreamRunData, InsightData, NoiseData } from '../../types/memory'
import {
  fetchMemoryStats,
  fetchMemoryAtoms,
  fetchMemoryAtomDetail,
  fetchDreamRuns,
  fetchInsights,
  fetchNoisePool,
} from '../../lib/api/memory-api'

/**
 * 噪声池完整数据（后端返回 ttl_days，前端类型暂未包含）
 */
interface NoisePoolItem extends NoiseData {
  ttl_days?: number
}

const ATOM_TYPES = [
  { value: 'all', label: '全部' },
  { value: 'episodic', label: '情景记忆' },
  { value: 'factual', label: '事实记忆' },
  { value: 'relational', label: '关系记忆' },
  { value: 'preference', label: '偏好记忆' },
  { value: 'planned', label: '计划记忆' },
]

const ATOM_STATUSES = [
  { value: 'active', label: '活跃' },
  { value: 'archived', label: '已归档' },
  { value: 'forgotten', label: '已遗忘' },
]

const PAGE_SIZE_OPTIONS = [
  { value: '10', label: '10' },
  { value: '20', label: '20' },
  { value: '50', label: '50' },
  { value: '100', label: '100' },
]

const TYPE_COLORS: Record<string, string> = {
  episodic: 'bg-blue-600 hover:bg-blue-700',
  factual: 'bg-green-600 hover:bg-green-700',
  relational: 'bg-purple-600 hover:bg-purple-700',
  preference: 'bg-amber-600 hover:bg-amber-700',
  planned: 'bg-pink-600 hover:bg-pink-700',
}

const CHART_COLORS = [
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-5))',
]

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

function truncateText(text: string | null | undefined, maxLength: number): string {
  if (!text) return '-'
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}...`
}

function getAtomTypeLabel(type: string): string {
  return ATOM_TYPES.find((t) => t.value === type)?.label || type
}

function getAtomTypeBadgeClass(type: string): string {
  return TYPE_COLORS[type] || 'bg-slate-600 hover:bg-slate-700'
}

function getStatusBadgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'active':
    case 'completed':
      return 'default'
    case 'archived':
    case 'running':
      return 'secondary'
    case 'forgotten':
    case 'failed':
      return 'destructive'
    case 'pending':
      return 'outline'
    default:
      return 'secondary'
  }
}

function getDreamRunTypeBadgeClass(runType: string): string {
  switch (runType) {
    case 'daily':
      return 'bg-blue-600 hover:bg-blue-700'
    case 'weekly':
      return 'bg-purple-600 hover:bg-purple-700'
    case 'monthly':
      return 'bg-amber-600 hover:bg-amber-700'
    default:
      return 'bg-slate-600 hover:bg-slate-700'
  }
}

function getDreamRunTypeLabel(runType: string): string {
  switch (runType) {
    case 'daily':
      return '每日'
    case 'weekly':
      return '每周'
    case 'monthly':
      return '每月'
    default:
      return runType
  }
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <AlertCircle className="h-10 w-10 text-destructive mb-3" />
      <p className="text-sm text-muted-foreground mb-4 max-w-md">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="h-4 w-4 mr-2" />
        重试
      </Button>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="text-center py-12 text-muted-foreground">
      暂无数据
    </div>
  )
}

export function MemoryPage() {
  const { toast } = useToast()
  const [activeTab, setActiveTab] = useState('overview')

  // Overview
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)
  const [archivedCount, setArchivedCount] = useState(0)
  const [forgottenCount, setForgottenCount] = useState(0)
  const [countsLoading, setCountsLoading] = useState(true)
  const [recentDreams, setRecentDreams] = useState<DreamRunData[]>([])
  const [recentDreamsLoading, setRecentDreamsLoading] = useState(true)

  // Atoms
  const [atoms, setAtoms] = useState<AtomData[]>([])
  const [atomsLoading, setAtomsLoading] = useState(true)
  const [atomsError, setAtomsError] = useState<string | null>(null)
  const [atomsTotal, setAtomsTotal] = useState(0)
  const [atomTypeFilter, setAtomTypeFilter] = useState('all')
  const [atomStatusFilter, setAtomStatusFilter] = useState('active')
  const [atomLimit, setAtomLimit] = useState(20)
  const [atomOffset, setAtomOffset] = useState(0)
  const [expandedAtomId, setExpandedAtomId] = useState<string | null>(null)
  const [expandedAtomDetail, setExpandedAtomDetail] = useState<AtomData | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Dreams
  const [dreams, setDreams] = useState<DreamRunData[]>([])
  const [dreamsLoading, setDreamsLoading] = useState(true)
  const [dreamsError, setDreamsError] = useState<string | null>(null)
  const [dreamsTotal, setDreamsTotal] = useState(0)
  const [dreamLimit, setDreamLimit] = useState(20)
  const [dreamOffset, setDreamOffset] = useState(0)

  // Insights
  const [insights, setInsights] = useState<InsightData[]>([])
  const [insightsLoading, setInsightsLoading] = useState(true)
  const [insightsError, setInsightsError] = useState<string | null>(null)
  const [insightsTotal, setInsightsTotal] = useState(0)
  const [insightLimit, setInsightLimit] = useState(20)
  const [insightOffset, setInsightOffset] = useState(0)

  // Noise
  const [noise, setNoise] = useState<NoisePoolItem[]>([])
  const [noiseLoading, setNoiseLoading] = useState(true)
  const [noiseError, setNoiseError] = useState<string | null>(null)
  const [noiseTotal, setNoiseTotal] = useState(0)
  const [noiseLimit, setNoiseLimit] = useState(20)
  const [noiseOffset, setNoiseOffset] = useState(0)

  const loadStats = useCallback(async () => {
    try {
      setStatsLoading(true)
      setStatsError(null)
      const data = await fetchMemoryStats()
      setStats(data)
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取记忆统计失败'
      setStatsError(message)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  const loadStatusCounts = useCallback(async () => {
    try {
      setCountsLoading(true)
      const [archived, forgotten] = await Promise.all([
        fetchMemoryAtoms({ status: 'archived', limit: 1 }),
        fetchMemoryAtoms({ status: 'forgotten', limit: 1 }),
      ])
      setArchivedCount(archived.total)
      setForgottenCount(forgotten.total)
    } catch (error) {
      console.error('加载状态计数失败:', error)
    } finally {
      setCountsLoading(false)
    }
  }, [])

  const loadRecentDreams = useCallback(async () => {
    try {
      setRecentDreamsLoading(true)
      const data = await fetchDreamRuns({ limit: 3 })
      setRecentDreams(data.items)
    } catch (error) {
      console.error('加载最近梦境运行失败:', error)
    } finally {
      setRecentDreamsLoading(false)
    }
  }, [])

  const loadAtoms = useCallback(async () => {
    try {
      setAtomsLoading(true)
      setAtomsError(null)
      const data = await fetchMemoryAtoms({
        atom_type: atomTypeFilter === 'all' ? undefined : atomTypeFilter,
        status: atomStatusFilter,
        limit: atomLimit,
        offset: atomOffset,
      })
      setAtoms(data.items)
      setAtomsTotal(data.total)
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取记忆原子列表失败'
      setAtomsError(message)
    } finally {
      setAtomsLoading(false)
    }
  }, [atomTypeFilter, atomStatusFilter, atomLimit, atomOffset])

  const loadDreams = useCallback(async () => {
    try {
      setDreamsLoading(true)
      setDreamsError(null)
      const data = await fetchDreamRuns({ limit: dreamLimit, offset: dreamOffset })
      setDreams(data.items)
      setDreamsTotal(data.total)
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取梦境运行记录失败'
      setDreamsError(message)
    } finally {
      setDreamsLoading(false)
    }
  }, [dreamLimit, dreamOffset])

  const loadInsights = useCallback(async () => {
    try {
      setInsightsLoading(true)
      setInsightsError(null)
      const data = await fetchInsights({ limit: insightLimit, offset: insightOffset })
      setInsights(data.items)
      setInsightsTotal(data.total)
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取洞见列表失败'
      setInsightsError(message)
    } finally {
      setInsightsLoading(false)
    }
  }, [insightLimit, insightOffset])

  const loadNoise = useCallback(async () => {
    try {
      setNoiseLoading(true)
      setNoiseError(null)
      const data = await fetchNoisePool({ limit: noiseLimit, offset: noiseOffset })
      setNoise(data.items as NoisePoolItem[])
      setNoiseTotal(data.total)
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取噪声池列表失败'
      setNoiseError(message)
    } finally {
      setNoiseLoading(false)
    }
  }, [noiseLimit, noiseOffset])

  useEffect(() => {
    loadStats()
    loadStatusCounts()
    loadRecentDreams()
  }, [loadStats, loadStatusCounts, loadRecentDreams])

  useEffect(() => {
    loadAtoms()
  }, [loadAtoms])

  useEffect(() => {
    loadDreams()
  }, [loadDreams])

  useEffect(() => {
    loadInsights()
  }, [loadInsights])

  useEffect(() => {
    loadNoise()
  }, [loadNoise])

  const handleAtomRowClick = async (atom: AtomData) => {
    if (expandedAtomId === atom.atom_id) {
      setExpandedAtomId(null)
      setExpandedAtomDetail(null)
      return
    }
    setExpandedAtomId(atom.atom_id)
    setDetailLoading(true)
    try {
      const detail = await fetchMemoryAtomDetail(atom.atom_id)
      setExpandedAtomDetail(detail)
    } catch (error) {
      const message = error instanceof Error ? error.message : '加载原子详情失败'
      toast({
        title: '加载详情失败',
        description: message,
        variant: 'destructive',
      })
      setExpandedAtomDetail(atom)
    } finally {
      setDetailLoading(false)
    }
  }

  const typeDistributionData = stats
    ? Object.entries(stats.type_distribution).map(([type, count]) => ({
        type: getAtomTypeLabel(type),
        count,
      }))
    : []

  const typeChartConfig: ChartConfig = Object.fromEntries(
    typeDistributionData.map((item, index) => [
      item.type,
      {
        label: item.type,
        color: CHART_COLORS[index % CHART_COLORS.length],
      },
    ])
  )

  const renderPagination = (
    offset: number,
    limit: number,
    total: number,
    onOffsetChange: (offset: number) => void,
    onLimitChange: (limit: number) => void
  ) => {
    const currentPage = Math.floor(offset / limit) + 1
    const totalPages = Math.max(1, Math.ceil(total / limit))
    const start = total === 0 ? 0 : offset + 1
    const end = Math.min(offset + limit, total)

    return (
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mt-4 pt-4 border-t">
        <div className="text-sm text-muted-foreground">
          显示 {start} 到 {end} 条，共 {total} 条
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={limit.toString()}
            onValueChange={(value) => {
              onLimitChange(parseInt(value))
              onOffsetChange(0)
            }}
          >
            <SelectTrigger className="w-20">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onOffsetChange(0)}
            disabled={currentPage === 1}
          >
            <ChevronsLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onOffsetChange(Math.max(0, offset - limit))}
            disabled={currentPage === 1}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground min-w-[80px] text-center">
            第 {currentPage} / {totalPages} 页
          </span>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onOffsetChange(offset + limit)}
            disabled={currentPage === totalPages}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onOffsetChange((totalPages - 1) * limit)}
            disabled={currentPage === totalPages}
          >
            <ChevronsRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    )
  }

  const renderOverviewSkeleton = () => (
    <div className="space-y-4">
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-8 w-16 mt-2" />
            </CardHeader>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-32" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-[250px] w-full" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-32" />
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )

  return (
    <div className={cn('h-[calc(100vh-4rem)] flex flex-col p-4 sm:p-6')}>
      {/* 页面标题 */}
      <div className="mb-4 sm:mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold flex items-center gap-2">
              <Brain className="h-8 w-8" strokeWidth={2} />
              记忆系统
            </h1>
            <p className="text-muted-foreground mt-1 text-sm sm:text-base">
              查看璃夜的记忆原子、梦境运行和洞察信息
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              loadStats()
              loadStatusCounts()
              loadRecentDreams()
              if (activeTab === 'atoms') loadAtoms()
              if (activeTab === 'dreams') loadDreams()
              if (activeTab === 'insights') {
                loadInsights()
                loadNoise()
              }
            }}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            刷新
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="pr-4 pb-6">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
            <TabsList className="grid w-full grid-cols-2 sm:grid-cols-4">
              <TabsTrigger value="overview">概览</TabsTrigger>
              <TabsTrigger value="atoms">记忆原子</TabsTrigger>
              <TabsTrigger value="dreams">梦境运行</TabsTrigger>
              <TabsTrigger value="insights">洞见与噪声</TabsTrigger>
            </TabsList>

            {/* 概览 */}
            <TabsContent value="overview" className="space-y-4">
              {statsLoading || countsLoading ? (
                renderOverviewSkeleton()
              ) : statsError ? (
                <ErrorState message={statsError} onRetry={() => {
                  loadStats()
                  loadStatusCounts()
                  loadRecentDreams()
                }} />
              ) : (
                <>
                  <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
                    <Card>
                      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">记忆原子总数</CardTitle>
                        <Database className="h-4 w-4 text-muted-foreground" />
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold">{stats?.total_atoms ?? 0}</div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">活跃原子</CardTitle>
                        <Zap className="h-4 w-4 text-muted-foreground" />
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-green-600">
                          {stats?.active_atoms ?? 0}
                        </div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">已归档</CardTitle>
                        <Clock className="h-4 w-4 text-muted-foreground" />
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-amber-600">{archivedCount}</div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">已遗忘</CardTitle>
                        <VolumeX className="h-4 w-4 text-muted-foreground" />
                      </CardHeader>
                      <CardContent>
                        <div className="text-2xl font-bold text-slate-500">{forgottenCount}</div>
                      </CardContent>
                    </Card>
                  </div>

                  <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
                    <Card>
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                          <BarChart3 className="h-5 w-5" />
                          记忆类型分布
                        </CardTitle>
                        <CardDescription>按记忆原子类型统计数量</CardDescription>
                      </CardHeader>
                      <CardContent>
                        {typeDistributionData.length === 0 ? (
                          <EmptyState />
                        ) : (
                          <ChartContainer
                            config={typeChartConfig}
                            className="h-[250px] sm:h-[300px] w-full aspect-auto"
                          >
                            <BarChart data={typeDistributionData}>
                              <CartesianGrid
                                strokeDasharray="3 3"
                                stroke="hsl(var(--muted-foreground) / 0.2)"
                              />
                              <XAxis
                                dataKey="type"
                                stroke="hsl(var(--muted-foreground))"
                                tick={{ fill: 'hsl(var(--muted-foreground))' }}
                              />
                              <YAxis
                                allowDecimals={false}
                                stroke="hsl(var(--muted-foreground))"
                                tick={{ fill: 'hsl(var(--muted-foreground))' }}
                              />
                              <ChartTooltip
                                content={
                                  <ChartTooltipContent
                                    labelFormatter={(label) => label as string}
                                  />
                                }
                              />
                              <Bar dataKey="count">
                                {typeDistributionData.map((_, index) => (
                                  <Cell
                                    key={`cell-${index}`}
                                    fill={CHART_COLORS[index % CHART_COLORS.length]}
                                  />
                                ))}
                              </Bar>
                            </BarChart>
                          </ChartContainer>
                        )}
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                          <Sparkles className="h-5 w-5" />
                          最近梦境运行
                        </CardTitle>
                        <CardDescription>最近 3 次梦境整理记录</CardDescription>
                      </CardHeader>
                      <CardContent>
                        {recentDreamsLoading ? (
                          <div className="space-y-3">
                            {Array.from({ length: 3 }).map((_, i) => (
                              <Skeleton key={i} className="h-16 w-full" />
                            ))}
                          </div>
                        ) : recentDreams.length === 0 ? (
                          <EmptyState />
                        ) : (
                          <div className="space-y-3">
                            {recentDreams.map((dream) => (
                              <div
                                key={dream.id}
                                className="p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
                              >
                                <div className="flex items-center justify-between gap-2 mb-1">
                                  <div className="flex items-center gap-2">
                                    <Badge className={getDreamRunTypeBadgeClass(dream.run_type)}>
                                      {getDreamRunTypeLabel(dream.run_type)}
                                    </Badge>
                                    <Badge variant={getStatusBadgeVariant(dream.status)}>
                                      {dream.status}
                                    </Badge>
                                  </div>
                                  <span className="text-xs text-muted-foreground">
                                    {formatDateTime(dream.start_time)}
                                  </span>
                                </div>
                                <p className="text-sm text-muted-foreground line-clamp-2">
                                  {truncateText(dream.summary, 80)}
                                </p>
                                <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                                  <span>处理: {dream.atoms_processed ?? 0}</span>
                                  <span>创建: {dream.atoms_created ?? 0}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                </>
              )}
            </TabsContent>

            {/* 记忆原子 */}
            <TabsContent value="atoms" className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Filter className="h-5 w-5" />
                    筛选
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="space-y-1.5">
                      <span className="text-sm font-medium">记忆类型</span>
                      <Select value={atomTypeFilter} onValueChange={(value) => {
                        setAtomTypeFilter(value)
                        setAtomOffset(0)
                      }}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ATOM_TYPES.map((type) => (
                            <SelectItem key={type.value} value={type.value}>
                              {type.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <span className="text-sm font-medium">状态</span>
                      <Select value={atomStatusFilter} onValueChange={(value) => {
                        setAtomStatusFilter(value)
                        setAtomOffset(0)
                      }}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ATOM_STATUSES.map((status) => (
                            <SelectItem key={status.value} value={status.value}>
                              {status.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <span className="text-sm font-medium">每页显示</span>
                      <Select
                        value={atomLimit.toString()}
                        onValueChange={(value) => {
                          setAtomLimit(parseInt(value))
                          setAtomOffset(0)
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PAGE_SIZE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>记忆原子列表</CardTitle>
                  <CardDescription>共 {atomsTotal} 个原子</CardDescription>
                </CardHeader>
                <CardContent>
                  {atomsLoading ? (
                    <div className="space-y-2">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} className="h-12 w-full" />
                      ))}
                    </div>
                  ) : atomsError ? (
                    <ErrorState message={atomsError} onRetry={loadAtoms} />
                  ) : atoms.length === 0 ? (
                    <EmptyState />
                  ) : (
                    <>
                      <div className="rounded-md border overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-[100px]">ID</TableHead>
                              <TableHead>类型</TableHead>
                              <TableHead>内容</TableHead>
                              <TableHead>状态</TableHead>
                              <TableHead>重要性</TableHead>
                              <TableHead>权重</TableHead>
                              <TableHead>创建时间</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {atoms.map((atom) => (
                              <Fragment key={atom.atom_id}>
                                <TableRow
                                  className="cursor-pointer hover:bg-accent/50"
                                  onClick={() => handleAtomRowClick(atom)}
                                >
                                  <TableCell className="font-mono text-xs">
                                    {truncateText(atom.atom_id, 12)}
                                  </TableCell>
                                  <TableCell>
                                    <Badge className={getAtomTypeBadgeClass(atom.atom_type)}>
                                      {getAtomTypeLabel(atom.atom_type)}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="max-w-xs truncate">
                                    {truncateText(atom.content, 60)}
                                  </TableCell>
                                  <TableCell>
                                    <Badge variant={getStatusBadgeVariant(atom.status)}>
                                      {atom.status}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="w-[120px]">
                                    <div className="flex items-center gap-2">
                                      <Progress value={atom.importance * 100} className="h-2" />
                                      <span className="text-xs text-muted-foreground w-10 text-right">
                                        {(atom.importance * 100).toFixed(0)}%
                                      </span>
                                    </div>
                                  </TableCell>
                                  <TableCell className="w-[120px]">
                                    <div className="flex items-center gap-2">
                                      <Progress value={atom.weight * 100} className="h-2" />
                                      <span className="text-xs text-muted-foreground w-10 text-right">
                                        {(atom.weight * 100).toFixed(0)}%
                                      </span>
                                    </div>
                                  </TableCell>
                                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                                    {formatDateTime(atom.created_at)}
                                  </TableCell>
                                </TableRow>
                                {expandedAtomId === atom.atom_id && (
                                  <TableRow className="bg-accent/30">
                                    <TableCell colSpan={7} className="p-0">
                                      <div className="p-4">
                                        {detailLoading ? (
                                          <div className="space-y-2">
                                            <Skeleton className="h-4 w-full" />
                                            <Skeleton className="h-4 w-3/4" />
                                            <Skeleton className="h-4 w-1/2" />
                                          </div>
                                        ) : expandedAtomDetail ? (
                                          <div className="space-y-3">
                                            <div>
                                              <span className="text-xs text-muted-foreground">完整内容</span>
                                              <p className="text-sm mt-1">{expandedAtomDetail.content}</p>
                                            </div>
                                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                                              <div>
                                                <span className="text-xs text-muted-foreground">置信度</span>
                                                <p>{(expandedAtomDetail.confidence * 100).toFixed(1)}%</p>
                                              </div>
                                              <div>
                                                <span className="text-xs text-muted-foreground">来源场景</span>
                                                <p>{expandedAtomDetail.source_scene || '-'}</p>
                                              </div>
                                              <div>
                                                <span className="text-xs text-muted-foreground">状态</span>
                                                <p>
                                                  <Badge variant={getStatusBadgeVariant(expandedAtomDetail.status)}>
                                                    {expandedAtomDetail.status}
                                                  </Badge>
                                                </p>
                                              </div>
                                            </div>
                                            {expandedAtomDetail.entities && expandedAtomDetail.entities.length > 0 && (
                                              <div>
                                                <span className="text-xs text-muted-foreground">关联实体</span>
                                                <div className="flex flex-wrap gap-2 mt-1">
                                                  {expandedAtomDetail.entities.map((entity, index) => (
                                                    <Badge key={index} variant="outline">
                                                      {entity}
                                                    </Badge>
                                                  ))}
                                                </div>
                                              </div>
                                            )}
                                          </div>
                                        ) : null}
                                      </div>
                                    </TableCell>
                                  </TableRow>
                                )}
                              </Fragment>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                      {renderPagination(
                        atomOffset,
                        atomLimit,
                        atomsTotal,
                        setAtomOffset,
                        setAtomLimit
                      )}
                    </>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* 梦境运行 */}
            <TabsContent value="dreams" className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>梦境运行记录</CardTitle>
                  <CardDescription>记忆系统的梦境整理历史</CardDescription>
                </CardHeader>
                <CardContent>
                  {dreamsLoading ? (
                    <div className="space-y-2">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} className="h-12 w-full" />
                      ))}
                    </div>
                  ) : dreamsError ? (
                    <ErrorState message={dreamsError} onRetry={loadDreams} />
                  ) : dreams.length === 0 ? (
                    <EmptyState />
                  ) : (
                    <>
                      <div className="rounded-md border overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>ID</TableHead>
                              <TableHead>类型</TableHead>
                              <TableHead>开始时间</TableHead>
                              <TableHead>结束时间</TableHead>
                              <TableHead>状态</TableHead>
                              <TableHead>处理原子</TableHead>
                              <TableHead>创建原子</TableHead>
                              <TableHead>摘要</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {dreams.map((dream) => (
                              <TableRow key={dream.id}>
                                <TableCell className="font-mono text-xs">{dream.id}</TableCell>
                                <TableCell>
                                  <Badge className={getDreamRunTypeBadgeClass(dream.run_type)}>
                                    {getDreamRunTypeLabel(dream.run_type)}
                                  </Badge>
                                </TableCell>
                                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                                  {formatDateTime(dream.start_time)}
                                </TableCell>
                                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                                  {formatDateTime(dream.end_time)}
                                </TableCell>
                                <TableCell>
                                  <Badge variant={getStatusBadgeVariant(dream.status)}>
                                    {dream.status}
                                  </Badge>
                                </TableCell>
                                <TableCell>{dream.atoms_processed ?? 0}</TableCell>
                                <TableCell>{dream.atoms_created ?? 0}</TableCell>
                                <TableCell className="max-w-xs truncate">
                                  {truncateText(dream.summary, 40)}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                      {renderPagination(
                        dreamOffset,
                        dreamLimit,
                        dreamsTotal,
                        setDreamOffset,
                        setDreamLimit
                      )}
                    </>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* 洞见与噪声 */}
            <TabsContent value="insights" className="space-y-4">
              <div className="grid gap-4 grid-cols-1 xl:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Lightbulb className="h-5 w-5" />
                      洞见池
                    </CardTitle>
                    <CardDescription>从记忆原子中提炼的洞察</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {insightsLoading ? (
                      <div className="space-y-3">
                        {Array.from({ length: 4 }).map((_, i) => (
                          <Skeleton key={i} className="h-24 w-full" />
                        ))}
                      </div>
                    ) : insightsError ? (
                      <ErrorState message={insightsError} onRetry={loadInsights} />
                    ) : insights.length === 0 ? (
                      <EmptyState />
                    ) : (
                      <>
                        <ScrollArea className="h-[500px]">
                          <div className="space-y-3 pr-4">
                            {insights.map((insight) => (
                              <div
                                key={insight.id}
                                className="p-4 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
                              >
                                <p className="text-sm font-medium mb-2">{insight.content}</p>
                                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                                  <div>
                                    <span>来源原子: </span>
                                    <span className="font-medium">
                                      {insight.source_atoms?.length ?? 0}
                                    </span>
                                  </div>
                                  <div>
                                    <span>代理: </span>
                                    <span className="font-medium">{insight.agent_name || '-'}</span>
                                  </div>
                                  <div>
                                    <span>置信度: </span>
                                    <span className="font-medium">
                                      {insight.confidence !== null
                                        ? `${(insight.confidence * 100).toFixed(1)}%`
                                        : '-'}
                                    </span>
                                  </div>
                                  <div>
                                    <span>创建时间: </span>
                                    <span className="font-medium">
                                      {formatDateTime(insight.created_at)}
                                    </span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </ScrollArea>
                        {renderPagination(
                          insightOffset,
                          insightLimit,
                          insightsTotal,
                          setInsightOffset,
                          setInsightLimit
                        )}
                      </>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <VolumeX className="h-5 w-5" />
                      噪声池
                    </CardTitle>
                    <CardDescription>被识别为低价值的信息</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {noiseLoading ? (
                      <div className="space-y-3">
                        {Array.from({ length: 4 }).map((_, i) => (
                          <Skeleton key={i} className="h-24 w-full" />
                        ))}
                      </div>
                    ) : noiseError ? (
                      <ErrorState message={noiseError} onRetry={loadNoise} />
                    ) : noise.length === 0 ? (
                      <EmptyState />
                    ) : (
                      <>
                        <ScrollArea className="h-[500px]">
                          <div className="space-y-3 pr-4">
                            {noise.map((item) => (
                              <div
                                key={item.id}
                                className="p-4 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
                              >
                                <p className="text-sm font-medium mb-2">{item.content}</p>
                                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                                  <div>
                                    <span>来源场景: </span>
                                    <span className="font-medium">{item.source_scene || '-'}</span>
                                  </div>
                                  <div>
                                    <span>显著性: </span>
                                    <span className="font-medium">
                                      {item.significance !== null
                                        ? `${(item.significance * 100).toFixed(1)}%`
                                        : '-'}
                                    </span>
                                  </div>
                                  <div>
                                    <span>存活天数: </span>
                                    <span className="font-medium">{item.ttl_days ?? '-'} 天</span>
                                  </div>
                                  <div>
                                    <span>创建时间: </span>
                                    <span className="font-medium">
                                      {formatDateTime(item.created_at)}
                                    </span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </ScrollArea>
                        {renderPagination(
                          noiseOffset,
                          noiseLimit,
                          noiseTotal,
                          setNoiseOffset,
                          setNoiseLimit
                        )}
                      </>
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </ScrollArea>
    </div>
  )
}
