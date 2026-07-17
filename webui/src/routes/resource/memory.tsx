import { Fragment, useCallback, useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import {
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
  Check,
  Lightbulb,
  VolumeX,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DreamRunCard } from '@/components/memory/dream-run-card'
import { DreamRunMessageDialog } from '@/components/memory/dream-run-message-dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
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
import type {
  MemoryStats,
  AtomData,
  DreamRunData,
  InsightData,
  NoiseData,
} from '../../types/memory'
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

type MemoryTab = 'overview' | 'atoms' | 'dreams' | 'insights'

const MEMORY_TABS: Array<{
  value: MemoryTab
  label: string
  description: string
  Icon: LucideIcon
  color: string
}> = [
  {
    value: 'overview',
    label: '概览',
    description: '统计与最近梦境',
    Icon: BarChart3,
    color: 'ios-symbol-blue',
  },
  {
    value: 'atoms',
    label: '记忆原子',
    description: '查看和筛选记忆',
    Icon: Database,
    color: 'ios-symbol-green',
  },
  {
    value: 'dreams',
    label: '梦境运行',
    description: '整理任务历史',
    Icon: Sparkles,
    color: 'ios-symbol-purple',
  },
  {
    value: 'insights',
    label: '洞见与噪声',
    description: '洞察和噪声池',
    Icon: Lightbulb,
    color: 'ios-symbol-orange',
  },
]

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
  episodic:
    'bg-[rgb(0_122_255_/_0.12)] text-[rgb(0_84_166)] hover:bg-[rgb(0_122_255_/_0.16)] dark:bg-[rgb(10_132_255_/_0.18)] dark:text-[rgb(100_210_255)] dark:hover:bg-[rgb(10_132_255_/_0.22)]',
  factual:
    'bg-[rgb(52_199_89_/_0.12)] text-[rgb(36_138_61)] hover:bg-[rgb(52_199_89_/_0.16)] dark:bg-[rgb(48_209_88_/_0.18)] dark:text-[rgb(48_209_88)] dark:hover:bg-[rgb(48_209_88_/_0.22)]',
  relational:
    'bg-[rgb(88_86_214_/_0.12)] text-[rgb(54_52_163)] hover:bg-[rgb(88_86_214_/_0.16)] dark:bg-[rgb(191_90_242_/_0.18)] dark:text-[rgb(191_90_242)] dark:hover:bg-[rgb(191_90_242_/_0.22)]',
  preference:
    'bg-[rgb(255_149_0_/_0.14)] text-[rgb(172_96_0)] hover:bg-[rgb(255_149_0_/_0.18)] dark:bg-[rgb(255_159_10_/_0.2)] dark:text-[rgb(255_159_10)] dark:hover:bg-[rgb(255_159_10_/_0.24)]',
  planned:
    'bg-[rgb(255_45_85_/_0.12)] text-[rgb(184_31_58)] hover:bg-[rgb(255_45_85_/_0.16)] dark:bg-[rgb(255_55_95_/_0.18)] dark:text-[rgb(255_55_95)] dark:hover:bg-[rgb(255_55_95_/_0.22)]',
}

const CHART_COLORS = [
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-5))',
]

const memorySelectTriggerClass =
  'h-auto min-h-11 w-full min-w-11 justify-between gap-2 rounded-[14px] border-0 bg-secondary/60 px-3 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-secondary/70 focus:ring-0 sm:w-auto sm:justify-end sm:gap-1 sm:bg-transparent sm:px-0 sm:hover:bg-transparent [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4'

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
  return (
    TYPE_COLORS[type] ||
    'bg-[rgb(142_142_147_/_0.14)] text-[rgb(99_99_102)] hover:bg-[rgb(142_142_147_/_0.18)] dark:bg-[rgb(142_142_147_/_0.2)] dark:text-[rgb(174_174_178)] dark:hover:bg-[rgb(142_142_147_/_0.24)]'
  )
}

function getStatusBadgeVariant(
  status: string
): 'default' | 'secondary' | 'destructive' | 'outline' {
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

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <AlertCircle className="text-destructive mb-3 h-10 w-10" />
      <p className="mb-4 max-w-md text-sm text-muted-foreground">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="mr-2 h-4 w-4" />
        重试
      </Button>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="ios-empty-state min-h-[180px]">
      <span className="ios-empty-illustration">
        <Database className="relative z-10 h-7 w-7 text-primary" />
      </span>
      <div>
        <p className="text-[16px] font-semibold leading-6 text-foreground">暂无数据</p>
        <p className="mt-1 max-w-sm text-[13px] leading-5 text-muted-foreground">
          有新的记忆记录后会在这里显示。
        </p>
      </div>
    </div>
  )
}

export function MemoryPage() {
  const { toast } = useToast()
  const [activeTab, setActiveTab] = useState<MemoryTab>('overview')
  const [viewDialogOpen, setViewDialogOpen] = useState(false)
  const activeTabItem = MEMORY_TABS.find((item) => item.value === activeTab) ?? MEMORY_TABS[0]

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
  const [selectedDream, setSelectedDream] = useState<DreamRunData | null>(null)
  const [dreamDetailsOpen, setDreamDetailsOpen] = useState(false)

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

  const handleOpenDreamDetails = (dream: DreamRunData) => {
    setSelectedDream(dream)
    setDreamDetailsOpen(true)
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
      <div className="ios-row ios-row-plain min-h-[68px] flex-col !items-stretch !justify-start gap-3 border-t border-border/60 sm:flex-row sm:!items-center sm:!justify-between">
        <div className="text-sm text-muted-foreground">
          显示 {start} 到 {end} 条，共 {total} 条
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
          <Select
            value={limit.toString()}
            onValueChange={(value) => {
              onLimitChange(parseInt(value))
              onOffsetChange(0)
            }}
          >
            <SelectTrigger className={cn(memorySelectTriggerClass, 'sm:max-w-[6rem]')}>
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
            className="hidden h-11 w-11 rounded-full sm:inline-flex"
          >
            <ChevronsLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onOffsetChange(Math.max(0, offset - limit))}
            disabled={currentPage === 1}
            className="h-11 w-11 rounded-full"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-[80px] text-center text-sm text-muted-foreground">
            第 {currentPage} / {totalPages} 页
          </span>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onOffsetChange(offset + limit)}
            disabled={currentPage === totalPages}
            className="h-11 w-11 rounded-full"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onOffsetChange((totalPages - 1) * limit)}
            disabled={currentPage === totalPages}
            className="hidden h-11 w-11 rounded-full sm:inline-flex"
          >
            <ChevronsRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    )
  }

  const renderOverviewSkeleton = () => (
    <div className="space-y-4">
      <div className="ios-group overflow-hidden sm:hidden">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="ios-row">
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <Skeleton className="h-8 w-8 shrink-0 rounded-[9px]" />
              <Skeleton className="h-4 w-28" />
            </div>
            <Skeleton className="h-5 w-10" />
          </div>
        ))}
      </div>
      <div className="hidden grid-cols-2 gap-4 sm:grid lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="ios-stat-card">
            <div className="space-y-3">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="mt-2 h-8 w-16" />
            </div>
          </div>
        ))}
      </div>
      <div className="hidden grid-cols-1 gap-4 sm:grid lg:grid-cols-2">
        <div className="ios-group p-5">
          <div className="mb-4">
            <Skeleton className="h-5 w-32" />
          </div>
          <div>
            <Skeleton className="h-[250px] w-full" />
          </div>
        </div>
        <div className="ios-group p-5">
          <div className="mb-4">
            <Skeleton className="h-5 w-32" />
          </div>
          <div>
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <div className={cn('ios-page flex h-[calc(100vh-4rem)] flex-col')}>
      {/* 页面标题 */}
      <div className="mb-5 sm:mb-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">记忆系统</h1>
            <p className="ios-subtitle">查看当前实例的记忆原子、梦境运行和洞察信息</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="hidden sm:inline-flex"
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
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
        </div>
        <button
          type="button"
          className="ios-group ios-touch mt-5 flex w-full items-center justify-between gap-3 px-4 py-3 text-left focus-visible:ring-0 sm:hidden"
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
          <span className="flex min-w-0 flex-1 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
              <RefreshCw className="h-4 w-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-medium leading-5">刷新</span>
              <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                更新记忆统计和列表
              </span>
            </span>
          </span>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-5 pb-6 pr-0 sm:space-y-4 sm:pr-4">
          <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="ios-group ios-touch mb-4 flex w-full items-center justify-between gap-4 px-4 py-3 text-left focus-visible:ring-0 sm:hidden"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span className={cn('ios-symbol ios-symbol-sm', activeTabItem.color)}>
                    <activeTabItem.Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5 text-foreground">
                      当前视图
                    </span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      {activeTabItem.label} · {activeTabItem.description}
                    </span>
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </DialogTrigger>
            <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
              <DialogHeader className="px-5 pb-1 pt-5">
                <DialogTitle>记忆系统视图</DialogTitle>
                <DialogDescription>选择要查看的记忆信息</DialogDescription>
              </DialogHeader>
              <div className="px-5 pb-5">
                <div className="ios-group overflow-hidden">
                  {MEMORY_TABS.map((item) => {
                    const selected = item.value === activeTab
                    return (
                      <button
                        key={item.value}
                        type="button"
                        className="ios-touch flex min-h-[62px] w-full items-center justify-between gap-3 border-b border-border/70 px-4 py-3 text-left last:border-b-0 hover:bg-accent/55"
                        aria-current={selected ? 'page' : undefined}
                        onClick={() => {
                          setActiveTab(item.value)
                          setViewDialogOpen(false)
                        }}
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span className={cn('ios-symbol ios-symbol-sm', item.color)}>
                            <item.Icon className="h-4 w-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[15px] font-medium leading-5 text-foreground">
                              {item.label}
                            </span>
                            <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                              {item.description}
                            </span>
                          </span>
                        </span>
                        {selected ? (
                          <Check className="h-4 w-4 shrink-0 text-primary" />
                        ) : (
                          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/80" />
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            </DialogContent>
          </Dialog>

          <Tabs
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as MemoryTab)}
            className="space-y-4"
          >
            <TabsList className="hidden w-full grid-cols-2 sm:grid sm:grid-cols-4">
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
                <ErrorState
                  message={statsError}
                  onRetry={() => {
                    loadStats()
                    loadStatusCounts()
                    loadRecentDreams()
                  }}
                />
              ) : (
                <>
                  <div className="space-y-5 sm:hidden">
                    <div className="ios-group overflow-hidden">
                      <div className="ios-row">
                        <span className="flex min-w-0 flex-1 items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                            <Database className="h-4 w-4" />
                          </span>
                          <span className="truncate text-[15px] font-medium">记忆原子总数</span>
                        </span>
                        <span className="shrink-0 text-[17px] font-semibold tabular-nums">
                          {stats?.total_atoms ?? 0}
                        </span>
                      </div>
                      <div className="ios-row">
                        <span className="flex min-w-0 flex-1 items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                            <Zap className="h-4 w-4" />
                          </span>
                          <span className="truncate text-[15px] font-medium">活跃原子</span>
                        </span>
                        <span className="shrink-0 text-[17px] font-semibold tabular-nums text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]">
                          {stats?.active_atoms ?? 0}
                        </span>
                      </div>
                      <div className="ios-row">
                        <span className="flex min-w-0 flex-1 items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                            <Clock className="h-4 w-4" />
                          </span>
                          <span className="truncate text-[15px] font-medium">已归档</span>
                        </span>
                        <span className="shrink-0 text-[17px] font-semibold tabular-nums text-[rgb(178_93_0)] dark:text-[rgb(255_159_10)]">
                          {archivedCount}
                        </span>
                      </div>
                      <div className="ios-row">
                        <span className="flex min-w-0 flex-1 items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                            <VolumeX className="h-4 w-4" />
                          </span>
                          <span className="truncate text-[15px] font-medium">已遗忘</span>
                        </span>
                        <span className="shrink-0 text-[17px] font-semibold tabular-nums text-muted-foreground">
                          {forgottenCount}
                        </span>
                      </div>
                    </div>

                    <div className="ios-group overflow-hidden">
                      <div className="ios-row">
                        <span className="flex min-w-0 flex-1 items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                            <BarChart3 className="h-4 w-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-[15px] font-medium">
                              记忆类型分布
                            </span>
                            <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                              {typeDistributionData.length > 0
                                ? `${typeDistributionData.length} 类记忆`
                                : '暂无数据'}
                            </span>
                          </span>
                        </span>
                      </div>
                      <div className="ios-row">
                        <span className="flex min-w-0 flex-1 items-center gap-3">
                          <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                            <Sparkles className="h-4 w-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-[15px] font-medium">
                              最近梦境运行
                            </span>
                            <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                              {recentDreamsLoading
                                ? '正在加载'
                                : recentDreams.length > 0
                                  ? `${recentDreams.length} 条最近记录`
                                  : '暂无记录'}
                            </span>
                          </span>
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="hidden grid-cols-2 gap-4 sm:grid lg:grid-cols-4">
                    {[
                      {
                        label: '记忆原子总数',
                        value: stats?.total_atoms ?? 0,
                        detail: '全部原子',
                        Icon: Database,
                        symbolClassName: 'ios-symbol-blue',
                      },
                      {
                        label: '活跃原子',
                        value: stats?.active_atoms ?? 0,
                        detail: '可用于召回',
                        Icon: Zap,
                        symbolClassName: 'ios-symbol-green',
                      },
                      {
                        label: '已归档',
                        value: archivedCount,
                        detail: '低频保留',
                        Icon: Clock,
                        symbolClassName: 'ios-symbol-orange',
                      },
                      {
                        label: '已遗忘',
                        value: forgottenCount,
                        detail: '不再召回',
                        Icon: VolumeX,
                        symbolClassName: 'ios-symbol-gray',
                      },
                    ].map(({ label, value, detail, Icon, symbolClassName }) => (
                      <div key={label} className="ios-stat-card">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                              {label}
                            </p>
                            <p className="mt-1 truncate text-[12px] leading-5 text-muted-foreground/80">
                              {detail}
                            </p>
                          </div>
                          <span className={`ios-symbol ios-symbol-sm ${symbolClassName}`}>
                            <Icon className="h-4 w-4" />
                          </span>
                        </div>
                        <p className="mt-5 truncate text-[28px] font-semibold tabular-nums leading-none tracking-normal">
                          {value}
                        </p>
                      </div>
                    ))}
                  </div>

                  <div className="hidden grid-cols-1 gap-4 sm:grid lg:grid-cols-2">
                    <div className="ios-group p-5">
                      <div className="mb-4 flex items-center gap-3">
                        <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                          <BarChart3 className="h-4 w-4" />
                        </span>
                        <div>
                          <h3 className="text-[16px] font-semibold leading-6">记忆类型分布</h3>
                          <p className="text-[13px] leading-5 text-muted-foreground">
                            按记忆原子类型统计数量
                          </p>
                        </div>
                      </div>
                      <div>
                        {typeDistributionData.length === 0 ? (
                          <EmptyState />
                        ) : (
                          <ChartContainer
                            config={typeChartConfig}
                            className="aspect-auto h-[250px] w-full sm:h-[300px]"
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
                      </div>
                    </div>

                    <div className="ios-group p-5">
                      <div className="mb-4 flex items-center gap-3">
                        <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                          <Sparkles className="h-4 w-4" />
                        </span>
                        <div>
                          <h3 className="text-[16px] font-semibold leading-6">最近梦境运行</h3>
                          <p className="text-[13px] leading-5 text-muted-foreground">
                            最近 3 次梦境整理记录
                          </p>
                        </div>
                      </div>
                      <div>
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
                              <DreamRunCard
                                key={dream.id}
                                run={dream}
                                variant="compact"
                                onOpenDetails={handleOpenDreamDetails}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </TabsContent>

            {/* 记忆原子 */}
            <TabsContent value="atoms" className="space-y-4">
              <div className="ios-group overflow-hidden">
                <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                      <Filter className="h-4 w-4" />
                    </span>
                    <span className="text-[16px] font-normal leading-6">记忆类型</span>
                  </span>
                  <Select
                    value={atomTypeFilter}
                    onValueChange={(value) => {
                      setAtomTypeFilter(value)
                      setAtomOffset(0)
                    }}
                  >
                    <SelectTrigger className={cn(memorySelectTriggerClass, 'sm:max-w-[8rem]')}>
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

                <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                      <Check className="h-4 w-4" />
                    </span>
                    <span className="text-[16px] font-normal leading-6">状态</span>
                  </span>
                  <Select
                    value={atomStatusFilter}
                    onValueChange={(value) => {
                      setAtomStatusFilter(value)
                      setAtomOffset(0)
                    }}
                  >
                    <SelectTrigger className={cn(memorySelectTriggerClass, 'sm:max-w-[8rem]')}>
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

                <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                      <Database className="h-4 w-4" />
                    </span>
                    <span className="text-[16px] font-normal leading-6">显示设置</span>
                  </span>
                  <Select
                    value={atomLimit.toString()}
                    onValueChange={(value) => {
                      setAtomLimit(parseInt(value))
                      setAtomOffset(0)
                    }}
                  >
                    <SelectTrigger className={cn(memorySelectTriggerClass, 'sm:max-w-[6rem]')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PAGE_SIZE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label} 条
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between px-1">
                  <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                    记忆原子列表
                  </p>
                  <span className="text-[13px] leading-5 text-muted-foreground">
                    共 {atomsTotal} 个
                  </span>
                </div>
                <div className="ios-group overflow-hidden">
                  {atomsLoading ? (
                    <div className="space-y-0">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className="ios-row">
                          <div className="flex min-w-0 flex-1 items-center gap-3">
                            <Skeleton className="h-8 w-8 shrink-0 rounded-[9px]" />
                            <div className="min-w-0 flex-1 space-y-2">
                              <Skeleton className="h-4 w-2/3" />
                              <Skeleton className="h-3 w-1/2" />
                            </div>
                          </div>
                          <Skeleton className="h-5 w-14" />
                        </div>
                      ))}
                    </div>
                  ) : atomsError ? (
                    <div className="ios-row ios-row-plain min-h-[132px] !justify-center">
                      <ErrorState message={atomsError} onRetry={loadAtoms} />
                    </div>
                  ) : atoms.length === 0 ? (
                    <div className="ios-row ios-row-plain min-h-[132px] !justify-center text-center text-muted-foreground">
                      暂无记忆原子
                    </div>
                  ) : (
                    <>
                      {atoms.map((atom) => (
                        <Fragment key={atom.atom_id}>
                          <button
                            type="button"
                            className="ios-row ios-touch min-h-[104px] w-full flex-col !items-stretch !justify-start gap-3 py-3 text-left sm:flex-row sm:!items-center sm:!justify-between"
                            onClick={() => handleAtomRowClick(atom)}
                          >
                            <span className="flex min-w-0 items-start gap-3">
                              <span className="ios-symbol ios-symbol-sm ios-symbol-green mt-0.5">
                                <Database className="h-4 w-4" />
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="flex min-w-0 flex-wrap items-center gap-2">
                                  <Badge
                                    variant="secondary"
                                    className={getAtomTypeBadgeClass(atom.atom_type)}
                                  >
                                    {getAtomTypeLabel(atom.atom_type)}
                                  </Badge>
                                  <Badge variant={getStatusBadgeVariant(atom.status)}>
                                    {ATOM_STATUSES.find((status) => status.value === atom.status)
                                      ?.label ?? atom.status}
                                  </Badge>
                                  <span className="font-mono text-[12px] leading-4 text-muted-foreground/80">
                                    {truncateText(atom.atom_id, 12)}
                                  </span>
                                </span>
                                <span className="mt-2 line-clamp-2 text-[15px] font-medium leading-5 text-foreground">
                                  {truncateText(atom.content, 96)}
                                </span>
                                <span className="mt-1 block text-[12px] leading-4 text-muted-foreground">
                                  {formatDateTime(atom.created_at)}
                                </span>
                              </span>
                            </span>
                            <span className="grid shrink-0 gap-2 pl-11 sm:w-56 sm:pl-0">
                              <span className="flex items-center gap-2">
                                <span className="w-12 text-[12px] leading-4 text-muted-foreground">
                                  重要性
                                </span>
                                <Progress value={atom.importance * 100} className="h-2" />
                                <span className="w-10 text-right text-[12px] tabular-nums text-muted-foreground">
                                  {(atom.importance * 100).toFixed(0)}%
                                </span>
                              </span>
                              <span className="flex items-center gap-2">
                                <span className="w-12 text-[12px] leading-4 text-muted-foreground">
                                  权重
                                </span>
                                <Progress value={atom.weight * 100} className="h-2" />
                                <span className="w-10 text-right text-[12px] tabular-nums text-muted-foreground">
                                  {(atom.weight * 100).toFixed(0)}%
                                </span>
                              </span>
                            </span>
                          </button>
                          {expandedAtomId === atom.atom_id && (
                            <div className="ios-row ios-row-plain min-h-[132px] !items-stretch !justify-start border-t border-border/60 bg-accent/25 py-4">
                              {detailLoading ? (
                                <div className="w-full space-y-2">
                                  <Skeleton className="h-4 w-full" />
                                  <Skeleton className="h-4 w-3/4" />
                                  <Skeleton className="h-4 w-1/2" />
                                </div>
                              ) : expandedAtomDetail ? (
                                <div className="w-full space-y-3">
                                  <div>
                                    <span className="text-xs text-muted-foreground">完整内容</span>
                                    <p className="mt-1 text-sm leading-6">
                                      {expandedAtomDetail.content}
                                    </p>
                                  </div>
                                  <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-3">
                                    <div>
                                      <span className="text-xs text-muted-foreground">置信度</span>
                                      <p>{(expandedAtomDetail.confidence * 100).toFixed(1)}%</p>
                                    </div>
                                    <div>
                                      <span className="text-xs text-muted-foreground">
                                        来源场景
                                      </span>
                                      <p>{expandedAtomDetail.source_scene || '-'}</p>
                                    </div>
                                    <div>
                                      <span className="text-xs text-muted-foreground">状态</span>
                                      <p>
                                        <Badge
                                          variant={getStatusBadgeVariant(expandedAtomDetail.status)}
                                        >
                                          {ATOM_STATUSES.find(
                                            (status) => status.value === expandedAtomDetail.status
                                          )?.label ?? expandedAtomDetail.status}
                                        </Badge>
                                      </p>
                                    </div>
                                  </div>
                                  {expandedAtomDetail.entities &&
                                    expandedAtomDetail.entities.length > 0 && (
                                      <div>
                                        <span className="text-xs text-muted-foreground">
                                          关联实体
                                        </span>
                                        <div className="mt-1 flex flex-wrap gap-2">
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
                          )}
                        </Fragment>
                      ))}
                      {renderPagination(
                        atomOffset,
                        atomLimit,
                        atomsTotal,
                        setAtomOffset,
                        setAtomLimit
                      )}
                    </>
                  )}
                </div>
              </div>
            </TabsContent>

            {/* 梦境运行 */}
            <TabsContent value="dreams" className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between px-1">
                  <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                    梦境运行记录
                  </p>
                  <span className="text-[13px] leading-5 text-muted-foreground">
                    共 {dreamsTotal} 条
                  </span>
                </div>
                {dreamsLoading ? (
                  <div className="ios-group overflow-hidden">
                    <div className="space-y-0">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className="ios-row">
                          <div className="flex min-w-0 flex-1 items-center gap-3">
                            <Skeleton className="h-8 w-8 shrink-0 rounded-[9px]" />
                            <div className="min-w-0 flex-1 space-y-2">
                              <Skeleton className="h-4 w-2/3" />
                              <Skeleton className="h-3 w-1/2" />
                            </div>
                          </div>
                          <Skeleton className="h-5 w-14" />
                        </div>
                      ))}
                    </div>
                  </div>
                ) : dreamsError ? (
                  <div className="ios-group overflow-hidden">
                    <div className="ios-row ios-row-plain min-h-[132px] !justify-center">
                      <ErrorState message={dreamsError} onRetry={loadDreams} />
                    </div>
                  </div>
                ) : dreams.length === 0 ? (
                  <div className="ios-group overflow-hidden">
                    <div className="ios-row ios-row-plain min-h-[132px] !justify-center text-center text-muted-foreground">
                      暂无梦境运行记录
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="space-y-3">
                      {dreams.map((dream) => (
                        <DreamRunCard
                          key={dream.id}
                          run={dream}
                          onOpenDetails={handleOpenDreamDetails}
                        />
                      ))}
                    </div>
                    <div className="ios-group mt-3 overflow-hidden">
                      {renderPagination(
                        dreamOffset,
                        dreamLimit,
                        dreamsTotal,
                        setDreamOffset,
                        setDreamLimit
                      )}
                    </div>
                  </>
                )}
              </div>
            </TabsContent>

            {/* 洞见与噪声 */}
            <TabsContent value="insights" className="space-y-4">
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <div className="ios-group p-5">
                  <div className="mb-4 flex items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                      <Lightbulb className="h-4 w-4" />
                    </span>
                    <div>
                      <h3 className="text-[16px] font-semibold leading-6">洞见池</h3>
                      <p className="text-[13px] leading-5 text-muted-foreground">
                        从记忆原子中提炼的洞察
                      </p>
                    </div>
                  </div>
                  <div>
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
                                className="ios-touch rounded-[16px] border border-border/45 bg-muted/35 p-4 hover:bg-accent/45"
                              >
                                <p className="mb-2 text-sm font-medium">{insight.content}</p>
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
                  </div>
                </div>

                <div className="ios-group p-5">
                  <div className="mb-4 flex items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                      <VolumeX className="h-4 w-4" />
                    </span>
                    <div>
                      <h3 className="text-[16px] font-semibold leading-6">噪声池</h3>
                      <p className="text-[13px] leading-5 text-muted-foreground">
                        被识别为低价值的信息
                      </p>
                    </div>
                  </div>
                  <div>
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
                                className="ios-touch rounded-[16px] border border-border/45 bg-muted/35 p-4 hover:bg-accent/45"
                              >
                                <p className="mb-2 text-sm font-medium">{item.content}</p>
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
                  </div>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </ScrollArea>
      <DreamRunMessageDialog
        key={selectedDream?.id ?? 'no-dream'}
        run={selectedDream}
        open={dreamDetailsOpen}
        onOpenChange={setDreamDetailsOpen}
      />
    </div>
  )
}
