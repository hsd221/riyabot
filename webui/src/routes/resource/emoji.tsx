import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Filter,
  Search,
  RefreshCw,
  Trash2,
  Edit,
  Info,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CheckCircle2,
  Ban,
  Upload,
  ArrowLeft,
  Check,
  X,
  ImageIcon,
  SlidersHorizontal,
  MoreHorizontal,
} from 'lucide-react'
import Uppy from '@uppy/core'
import Dashboard from '@uppy/react/dashboard'
import '@uppy/core/css/style.min.css'
import '@uppy/dashboard/css/style.min.css'
import '@/styles/uppy-custom.css'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EmojiThumbnail } from '@/components/emoji-thumbnail'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { IosGridSkeleton } from '@/components/ui/skeleton'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

import { Markdown } from '@/components/ui/markdown'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import type { Emoji, EmojiStats } from '@/types/emoji'
import {
  getEmojiList,
  getEmojiDetail,
  getEmojiStats,
  updateEmoji,
  deleteEmoji,
  registerEmoji,
  banEmoji,
  getEmojiThumbnailUrl,
  getEmojiOriginalUrl,
  batchDeleteEmojis,
  getEmojiUploadUrl,
} from '@/lib/emoji-api'

const SORT_OPTIONS = [
  { value: 'usage_count-desc', label: '使用次数', description: '多到少' },
  { value: 'usage_count-asc', label: '使用次数', description: '少到多' },
  { value: 'register_time-desc', label: '注册时间', description: '新到旧' },
  { value: 'register_time-asc', label: '注册时间', description: '旧到新' },
  { value: 'record_time-desc', label: '记录时间', description: '新到旧' },
  { value: 'record_time-asc', label: '记录时间', description: '旧到新' },
  { value: 'last_used_time-desc', label: '最后使用', description: '新到旧' },
  { value: 'last_used_time-asc', label: '最后使用', description: '旧到新' },
] as const

const REGISTER_OPTIONS = [
  { value: 'all', label: '全部', description: '不限注册状态' },
  { value: 'registered', label: '已注册', description: '只看已注册表情包' },
  { value: 'unregistered', label: '未注册', description: '只看未注册表情包' },
] as const

const BAN_OPTIONS = [
  { value: 'all', label: '全部', description: '不限封禁状态' },
  { value: 'banned', label: '已封禁', description: '只看已封禁表情包' },
  { value: 'unbanned', label: '未封禁', description: '只看未封禁表情包' },
] as const

const CARD_SIZE_OPTIONS = [
  { value: 'small', label: '小' },
  { value: 'medium', label: '中' },
  { value: 'large', label: '大' },
] as const

const PAGE_SIZE_OPTIONS = [20, 40, 60, 100] as const

const softGreenBadgeClass =
  'border-0 bg-[rgb(52_199_89_/_0.13)] text-[rgb(36_138_61)] shadow-[0_1px_0_rgba(255,255,255,0.5)_inset] dark:text-[rgb(48_209_88)]'
const softRedBadgeClass =
  'border-0 bg-[rgb(255_59_48_/_0.12)] text-[rgb(174_37_31)] shadow-[0_1px_0_rgba(255,255,255,0.42)_inset] dark:text-[rgb(255_105_97)]'

const emojiCardActionClass =
  'ios-touch flex min-h-[50px] w-full items-center gap-3 border-b border-border/45 px-3.5 py-2.5 text-left text-[15px] font-medium leading-5 last:border-b-0 hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:ring-0'

const emojiCardActionIconClass = 'ios-symbol ios-symbol-sm'

export function EmojiManagementPage() {
  const [emojiList, setEmojiList] = useState<Emoji[]>([])
  const [stats, setStats] = useState<EmojiStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [registeredFilter, setRegisteredFilter] = useState<string>('all')
  const [bannedFilter, setBannedFilter] = useState<string>('all')
  const [formatFilter, setFormatFilter] = useState<string>('all')
  const [sortBy, setSortBy] = useState<string>('usage_count')
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc')
  const [selectedEmoji, setSelectedEmoji] = useState<Emoji | null>(null)
  const [detailDialogOpen, setDetailDialogOpen] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [batchDeleteDialogOpen, setBatchDeleteDialogOpen] = useState(false)
  const [jumpToPage, setJumpToPage] = useState('')
  const [cardSize, setCardSize] = useState<'small' | 'medium' | 'large'>('medium')
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)

  const { toast } = useToast()

  // 加载表情包列表
  const loadEmojiList = useCallback(async () => {
    try {
      setLoading(true)
      const response = await getEmojiList({
        page,
        page_size: pageSize,
        search: search || undefined,
        is_registered: registeredFilter === 'all' ? undefined : registeredFilter === 'registered',
        is_banned: bannedFilter === 'all' ? undefined : bannedFilter === 'banned',
        format: formatFilter === 'all' ? undefined : formatFilter,
        sort_by: sortBy,
        sort_order: sortOrder,
      })
      setEmojiList(response.data)
      setTotal(response.total)
    } catch (error) {
      const message = error instanceof Error ? error.message : '加载表情包列表失败'
      toast({
        title: '错误',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [
    page,
    pageSize,
    search,
    registeredFilter,
    bannedFilter,
    formatFilter,
    sortBy,
    sortOrder,
    toast,
  ])

  // 加载统计数据
  const loadStats = async () => {
    try {
      const response = await getEmojiStats()
      setStats(response.data)
    } catch (error) {
      console.error('加载统计数据失败:', error)
    }
  }

  useEffect(() => {
    loadEmojiList()
  }, [loadEmojiList])

  useEffect(() => {
    loadStats()
  }, [])

  // 查看详情
  const handleViewDetail = async (emoji: Emoji) => {
    try {
      const response = await getEmojiDetail(emoji.id)
      setSelectedEmoji(response.data)
      setDetailDialogOpen(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : '加载详情失败'
      toast({
        title: '错误',
        description: message,
        variant: 'destructive',
      })
    }
  }

  // 编辑表情包
  const handleEdit = (emoji: Emoji) => {
    setSelectedEmoji(emoji)
    setEditDialogOpen(true)
  }

  // 删除表情包
  const handleDelete = (emoji: Emoji) => {
    setSelectedEmoji(emoji)
    setDeleteDialogOpen(true)
  }

  // 确认删除
  const confirmDelete = async () => {
    if (!selectedEmoji) return

    try {
      await deleteEmoji(selectedEmoji.id)
      toast({
        title: '成功',
        description: '表情包已删除',
      })
      setDeleteDialogOpen(false)
      setSelectedEmoji(null)
      loadEmojiList()
      loadStats()
    } catch (error) {
      const message = error instanceof Error ? error.message : '删除失败'
      toast({
        title: '错误',
        description: message,
        variant: 'destructive',
      })
    }
  }

  // 快速注册
  const handleRegister = async (emoji: Emoji) => {
    try {
      await registerEmoji(emoji.id)
      toast({
        title: '成功',
        description: '表情包已注册',
      })
      loadEmojiList()
      loadStats()
    } catch (error) {
      const message = error instanceof Error ? error.message : '注册失败'
      toast({
        title: '错误',
        description: message,
        variant: 'destructive',
      })
    }
  }

  // 快速封禁
  const handleBan = async (emoji: Emoji) => {
    try {
      await banEmoji(emoji.id)
      toast({
        title: '成功',
        description: '表情包已封禁',
      })
      loadEmojiList()
      loadStats()
    } catch (error) {
      const message = error instanceof Error ? error.message : '封禁失败'
      toast({
        title: '错误',
        description: message,
        variant: 'destructive',
      })
    }
  }

  // 切换选择
  const toggleSelect = (id: number) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelectedIds(newSelected)
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === emojiList.length && emojiList.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(emojiList.map((emoji) => emoji.id)))
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    try {
      const result = await batchDeleteEmojis(Array.from(selectedIds))
      toast({
        title: '批量删除完成',
        description: result.message,
      })
      setSelectedIds(new Set())
      setBatchDeleteDialogOpen(false)
      loadEmojiList()
      loadStats()
    } catch (error) {
      toast({
        title: '批量删除失败',
        description: error instanceof Error ? error.message : '批量删除失败',
        variant: 'destructive',
      })
    }
  }

  // 页面跳转
  const handleJumpToPage = () => {
    const targetPage = parseInt(jumpToPage)
    const totalPages = Math.ceil(total / pageSize)
    if (targetPage >= 1 && targetPage <= totalPages) {
      setPage(targetPage)
      setJumpToPage('')
    } else {
      toast({
        title: '无效的页码',
        description: `请输入1-${totalPages}之间的页码`,
        variant: 'destructive',
      })
    }
  }

  // 获取格式选项
  const formatOptions = stats?.formats ? Object.keys(stats.formats) : []
  const currentSortValue = `${sortBy}-${sortOrder}`
  const currentSortLabel =
    SORT_OPTIONS.find((option) => option.value === currentSortValue)?.label ?? '使用次数'
  const currentCardSizeLabel =
    CARD_SIZE_OPTIONS.find((option) => option.value === cardSize)?.label ?? '中'
  const currentRegisteredLabel =
    REGISTER_OPTIONS.find((option) => option.value === registeredFilter)?.label ?? '全部'
  const currentBannedLabel =
    BAN_OPTIONS.find((option) => option.value === bannedFilter)?.label ?? '全部'
  const currentFormatLabel = formatFilter === 'all' ? '全部格式' : formatFilter.toUpperCase()
  const activeFilterCount = [
    registeredFilter !== 'all',
    bannedFilter !== 'all',
    formatFilter !== 'all',
  ].filter(Boolean).length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const emojiStatItems = stats
    ? [
        {
          label: '总数',
          value: stats.total,
          detail: '全部资源',
          Icon: ImageIcon,
          symbolClassName: 'ios-symbol-blue',
        },
        {
          label: '已注册',
          value: stats.registered,
          detail: '可直接使用',
          Icon: CheckCircle2,
          symbolClassName: 'ios-symbol-green',
        },
        {
          label: '已封禁',
          value: stats.banned,
          detail: '不会被使用',
          Icon: Ban,
          symbolClassName: 'ios-symbol-red',
        },
        {
          label: '未注册',
          value: stats.unregistered,
          detail: '等待整理',
          Icon: X,
          symbolClassName: 'ios-symbol-gray',
        },
      ]
    : []

  return (
    <div className="flex h-[calc(100vh-4rem)] min-w-0 flex-col overflow-hidden px-5 py-5 sm:p-6">
      {/* 页面标题 */}
      <div className="mb-4 flex flex-col gap-4 sm:mb-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="ios-title">表情包管理</h1>
          <p className="ios-subtitle">管理当前实例的表情包资源</p>
        </div>
        <Button onClick={() => setUploadDialogOpen(true)} className="hidden gap-2 sm:inline-flex">
          <Upload className="h-4 w-4" />
          上传表情包
        </Button>
      </div>

      <ScrollArea className="min-w-0 flex-1">
        <div className="w-[calc(100vw-2.5rem)] max-w-full space-y-4 overflow-x-hidden sm:w-auto sm:space-y-6 sm:pr-4">
          <button
            type="button"
            onClick={() => setUploadDialogOpen(true)}
            className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                <Upload className="h-4 w-4" />
              </span>
              <span className="block min-w-0 truncate text-[16px] font-normal leading-6">
                上传表情包
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>

          {/* 统计 */}
          {stats && (
            <>
              <div className="ios-group max-w-full overflow-hidden sm:hidden">
                <div className="ios-scrollbar-none flex max-w-full gap-2 overflow-x-auto p-2">
                  {emojiStatItems.map(({ label, value, Icon, symbolClassName }) => (
                    <div
                      key={label}
                      className="flex min-w-[7.2rem] items-center gap-2 rounded-[16px] bg-[rgb(120_120_128_/_0.12)] px-3 py-2.5 shadow-[0_1px_0_rgba(255,255,255,0.54)_inset] dark:bg-white/[0.07] dark:shadow-[0_1px_0_rgba(255,255,255,0.06)_inset]"
                    >
                      <span className={`ios-symbol ${symbolClassName} h-7 w-7 rounded-[8px]`}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[18px] font-semibold tabular-nums leading-5 text-foreground">
                          {value}
                        </span>
                        <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                          {label}
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="hidden sm:grid sm:grid-cols-2 sm:gap-3 lg:grid-cols-4">
                {emojiStatItems.map(({ label, value, detail, Icon, symbolClassName }) => (
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
            </>
          )}

          <div className="ios-search-field max-w-full">
            <Search className="pointer-events-none absolute left-3.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="搜索描述或哈希"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(1)
              }}
              className="ios-search-input"
            />
          </div>

          {/* 筛选和显示 */}
          <Dialog open={filterDialogOpen} onOpenChange={setFilterDialogOpen}>
            <button
              type="button"
              onClick={() => setFilterDialogOpen(true)}
              className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">筛选与显示</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentSortLabel} · {currentRegisteredLabel} · {currentBannedLabel} ·{' '}
                    {currentFormatLabel}
                    {activeFilterCount > 0 ? ` · ${activeFilterCount} 个筛选` : ''}
                  </span>
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </button>

            <DialogContent className="max-h-[82vh] overflow-hidden sm:hidden">
              <DialogHeader>
                <DialogTitle>筛选与显示</DialogTitle>
                <DialogDescription>调整排序、状态筛选和网格密度</DialogDescription>
              </DialogHeader>
              <ScrollArea className="max-h-[calc(82vh-9rem)]">
                <div className="ios-group mb-5 overflow-hidden">
                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                        <Filter className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[16px] font-normal leading-6">排序</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          {currentSortLabel}
                        </span>
                      </span>
                    </span>
                    <Select
                      value={currentSortValue}
                      onValueChange={(value) => {
                        const [newSortBy, newSortOrder] = value.split('-')
                        setSortBy(newSortBy)
                        setSortOrder(newSortOrder as 'desc' | 'asc')
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[12rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SORT_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label} · {option.description}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                        <CheckCircle2 className="h-4 w-4" />
                      </span>
                      <span className="text-[16px] font-normal leading-6">注册状态</span>
                    </span>
                    <Select
                      value={registeredFilter}
                      onValueChange={(value) => {
                        setRegisteredFilter(value)
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {REGISTER_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-red">
                        <Ban className="h-4 w-4" />
                      </span>
                      <span className="text-[16px] font-normal leading-6">封禁状态</span>
                    </span>
                    <Select
                      value={bannedFilter}
                      onValueChange={(value) => {
                        setBannedFilter(value)
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {BAN_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                        <ImageIcon className="h-4 w-4" />
                      </span>
                      <span className="text-[16px] font-normal leading-6">格式</span>
                    </span>
                    <Select
                      value={formatFilter}
                      onValueChange={(value) => {
                        setFormatFilter(value)
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部格式</SelectItem>
                        {formatOptions.map((format) => (
                          <SelectItem key={format} value={format}>
                            {format.toUpperCase()} ({stats?.formats[format] ?? 0})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="ios-group overflow-hidden">
                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                        <SlidersHorizontal className="h-4 w-4" />
                      </span>
                      <span className="text-[16px] font-normal leading-6">卡片大小</span>
                    </span>
                    <Select
                      value={cardSize}
                      onValueChange={(value: 'small' | 'medium' | 'large') => setCardSize(value)}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[6rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {CARD_SIZE_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}卡片
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                        <MoreHorizontal className="h-4 w-4" />
                      </span>
                      <span className="text-[16px] font-normal leading-6">每页数量</span>
                    </span>
                    <Select
                      value={pageSize.toString()}
                      onValueChange={(value) => {
                        setPageSize(parseInt(value))
                        setPage(1)
                        setSelectedIds(new Set())
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[6rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PAGE_SIZE_OPTIONS.map((size) => (
                          <SelectItem key={size} value={size.toString()}>
                            {size} 条
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </ScrollArea>
              <DialogFooter>
                <Button onClick={() => setFilterDialogOpen(false)} className="w-full">
                  完成
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <div className="ios-group hidden overflow-hidden sm:block">
            <div className="ios-row min-h-[64px]">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                  <Filter className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">排序</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentSortLabel}
                  </span>
                </span>
              </span>
              <Select
                value={currentSortValue}
                onValueChange={(value) => {
                  const [newSortBy, newSortOrder] = value.split('-')
                  setSortBy(newSortBy)
                  setSortOrder(newSortOrder as 'desc' | 'asc')
                  setPage(1)
                }}
              >
                <SelectTrigger className="h-auto min-h-11 w-auto max-w-[12rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 sm:max-w-[16rem] [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SORT_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label} · {option.description}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[64px]">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                  <CheckCircle2 className="h-4 w-4" />
                </span>
                <span className="text-[16px] font-normal leading-6">注册状态</span>
              </span>
              <Select
                value={registeredFilter}
                onValueChange={(value) => {
                  setRegisteredFilter(value)
                  setPage(1)
                }}
              >
                <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {REGISTER_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[64px]">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-red">
                  <Ban className="h-4 w-4" />
                </span>
                <span className="text-[16px] font-normal leading-6">封禁状态</span>
              </span>
              <Select
                value={bannedFilter}
                onValueChange={(value) => {
                  setBannedFilter(value)
                  setPage(1)
                }}
              >
                <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BAN_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[64px]">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                  <ImageIcon className="h-4 w-4" />
                </span>
                <span className="text-[16px] font-normal leading-6">格式</span>
              </span>
              <Select
                value={formatFilter}
                onValueChange={(value) => {
                  setFormatFilter(value)
                  setPage(1)
                }}
              >
                <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部格式</SelectItem>
                  {formatOptions.map((format) => (
                    <SelectItem key={format} value={format}>
                      {format.toUpperCase()} ({stats?.formats[format] ?? 0})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[68px] flex-col !items-stretch !justify-start gap-3 py-3 sm:flex-row sm:!items-center sm:!justify-between">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">显示设置</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentCardSizeLabel}卡片 · 每页 {pageSize} 条 · 已选 {selectedIds.size}
                  </span>
                </span>
              </span>
              <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
                <Select
                  value={cardSize}
                  onValueChange={(value: 'small' | 'medium' | 'large') => setCardSize(value)}
                >
                  <SelectTrigger className="h-auto min-h-11 w-auto max-w-[6rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CARD_SIZE_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}卡片
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={pageSize.toString()}
                  onValueChange={(value) => {
                    setPageSize(parseInt(value))
                    setPage(1)
                    setSelectedIds(new Set())
                  }}
                >
                  <SelectTrigger className="h-auto min-h-11 w-auto max-w-[6rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PAGE_SIZE_OPTIONS.map((size) => (
                      <SelectItem key={size} value={size.toString()}>
                        {size} 条
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={loadEmojiList}
                  disabled={loading}
                  className="h-11 w-11 rounded-full"
                  title="刷新"
                >
                  <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                </Button>
                {selectedIds.size > 0 && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedIds(new Set())}
                      className="h-11 rounded-full px-4"
                    >
                      取消选择
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => setBatchDeleteDialogOpen(true)}
                      className="h-11 rounded-full px-4"
                    >
                      <Trash2 className="mr-1 h-4 w-4" />
                      批量删除
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* 表情包卡片列表 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">表情包列表</p>
              {emojiList.length > 0 && (
                <button
                  type="button"
                  onClick={toggleSelectAll}
                  className="ios-touch min-h-11 rounded-full px-3.5 py-2 text-[13px] font-medium leading-5 text-primary hover:bg-accent/60"
                >
                  {selectedIds.size === emojiList.length ? '取消全选' : '全选'}
                </button>
              )}
            </div>
            <div className="ios-group overflow-hidden">
              <div>
                {/* 卡片网格视图 */}
                {loading ? (
                  <IosGridSkeleton />
                ) : emojiList.length === 0 ? (
                  <div className="ios-empty-state">
                    <span className="ios-empty-illustration">
                      <ImageIcon className="relative z-10 h-7 w-7 text-primary" />
                    </span>
                    <div>
                      <p className="text-[16px] font-semibold leading-6 text-foreground">
                        暂无表情包
                      </p>
                      <p className="mt-1 max-w-sm text-[13px] leading-5">
                        上传图片后，可以在这里统一注册、封禁和整理表情资源。
                      </p>
                    </div>
                    <Button
                      onClick={() => setUploadDialogOpen(true)}
                      size="sm"
                      className="h-11 px-5"
                    >
                      <Upload className="mr-1 h-4 w-4" />
                      上传表情包
                    </Button>
                  </div>
                ) : (
                  <div
                    className={cn(
                      'grid min-w-0 gap-3 p-3 sm:p-4',
                      cardSize === 'small'
                        ? 'grid-cols-[repeat(3,minmax(0,1fr))] sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10'
                        : cardSize === 'medium'
                          ? 'grid-cols-[repeat(2,minmax(0,1fr))] sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8'
                          : 'grid-cols-[repeat(2,minmax(0,1fr))] sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5'
                    )}
                  >
                    {emojiList.map((emoji) => (
                      <div
                        key={emoji.id}
                        className={cn(
                          'ios-touch group relative min-w-0 cursor-pointer overflow-hidden rounded-[18px] border border-black/[0.035] bg-card shadow-[0_1px_0_rgba(255,255,255,0.72)_inset,0_10px_26px_rgba(31,41,55,0.055),0_2px_6px_rgba(0,0,0,0.024)] hover:ring-2 hover:ring-primary/60 active:scale-[0.98] active:shadow-[0_1px_0_rgba(255,255,255,0.5)_inset,0_4px_14px_rgba(31,41,55,0.06)] dark:border-white/10 dark:bg-card',
                          selectedIds.has(emoji.id) && 'bg-primary/5 ring-2 ring-primary'
                        )}
                        onClick={() => toggleSelect(emoji.id)}
                      >
                        {/* 选中指示器 */}
                        <div
                          className={`absolute left-1 top-1 z-10 transition-opacity ${
                            selectedIds.has(emoji.id)
                              ? 'opacity-100'
                              : 'opacity-0 group-hover:opacity-100'
                          }`}
                        >
                          <div
                            className={`flex h-7 w-7 items-center justify-center rounded-full border-2 shadow-[0_4px_12px_rgba(0,0,0,0.12)] ${
                              selectedIds.has(emoji.id)
                                ? 'border-primary bg-primary text-primary-foreground'
                                : 'border-muted-foreground/40 bg-background/90'
                            }`}
                          >
                            {selectedIds.has(emoji.id) && <CheckCircle2 className="h-4 w-4" />}
                          </div>
                        </div>

                        {/* 状态标签 */}
                        <div className="absolute right-1 top-1 z-10 flex flex-col gap-0.5">
                          {emoji.is_registered && (
                            <Badge
                              variant="secondary"
                              className={cn('px-1.5 py-0 text-[10px]', softGreenBadgeClass)}
                            >
                              已注册
                            </Badge>
                          )}
                          {emoji.is_banned && (
                            <Badge
                              variant="secondary"
                              className={cn('px-1.5 py-0 text-[10px]', softRedBadgeClass)}
                            >
                              已封禁
                            </Badge>
                          )}
                        </div>

                        {/* 图片 */}
                        <div
                          className={`flex aspect-square items-center justify-center overflow-hidden bg-muted/70 ${
                            cardSize === 'small' ? 'p-1' : cardSize === 'medium' ? 'p-2' : 'p-3'
                          }`}
                        >
                          <EmojiThumbnail src={getEmojiThumbnailUrl(emoji.id)} alt="表情包" />
                        </div>

                        {/* 底部信息和操作 */}
                        <div
                          className={`border-t border-border/55 bg-secondary/45 ${
                            cardSize === 'small' ? 'p-2' : 'p-2.5'
                          }`}
                        >
                          <div className="flex min-h-11 items-center justify-between gap-2">
                            <div className="min-w-0 text-xs text-muted-foreground">
                              <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                                {emoji.format.toUpperCase()}
                              </Badge>
                              <p className="mt-1 truncate font-mono">{emoji.usage_count} 次</p>
                            </div>

                            <Popover>
                              <PopoverTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-11 w-11 shrink-0 rounded-[14px]"
                                  onClick={(e) => e.stopPropagation()}
                                  title="更多操作"
                                >
                                  <MoreHorizontal className="h-5 w-5" />
                                </Button>
                              </PopoverTrigger>
                              <PopoverContent align="end" side="top" className="w-52 p-1.5">
                                <div className="overflow-hidden rounded-[14px]">
                                  <button
                                    type="button"
                                    className={emojiCardActionClass}
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      handleEdit(emoji)
                                    }}
                                  >
                                    <span
                                      className={cn(emojiCardActionIconClass, 'ios-symbol-blue')}
                                    >
                                      <Edit className="h-[18px] w-[18px]" />
                                    </span>
                                    编辑
                                  </button>
                                  <button
                                    type="button"
                                    className={emojiCardActionClass}
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      handleViewDetail(emoji)
                                    }}
                                  >
                                    <span
                                      className={cn(emojiCardActionIconClass, 'ios-symbol-gray')}
                                    >
                                      <Info className="h-[18px] w-[18px]" />
                                    </span>
                                    详情
                                  </button>
                                  {!emoji.is_registered && (
                                    <button
                                      type="button"
                                      className={emojiCardActionClass}
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleRegister(emoji)
                                      }}
                                    >
                                      <span
                                        className={cn(emojiCardActionIconClass, 'ios-symbol-green')}
                                      >
                                        <CheckCircle2 className="h-[18px] w-[18px]" />
                                      </span>
                                      注册
                                    </button>
                                  )}
                                  {!emoji.is_banned && (
                                    <button
                                      type="button"
                                      className={emojiCardActionClass}
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleBan(emoji)
                                      }}
                                    >
                                      <span
                                        className={cn(
                                          emojiCardActionIconClass,
                                          'ios-symbol-orange'
                                        )}
                                      >
                                        <Ban className="h-[18px] w-[18px]" />
                                      </span>
                                      封禁
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    className={cn(emojiCardActionClass, 'text-destructive')}
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      handleDelete(emoji)
                                    }}
                                  >
                                    <span
                                      className={cn(emojiCardActionIconClass, 'ios-symbol-red')}
                                    >
                                      <Trash2 className="h-[18px] w-[18px]" />
                                    </span>
                                    删除
                                  </button>
                                </div>
                              </PopoverContent>
                            </Popover>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* 分页 */}
                {total > 0 && (
                  <div className="ios-row ios-row-plain min-h-[68px] flex-col !items-stretch !justify-start gap-3 border-t border-border/60 sm:flex-row sm:!items-center sm:!justify-between">
                    <div className="text-sm text-muted-foreground">
                      共 {total} 个表情包，第 {page} / {totalPages} 页
                    </div>
                    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => setPage(1)}
                        disabled={page === 1}
                        className="hidden h-11 w-11 rounded-full sm:inline-flex"
                      >
                        <ChevronsLeft className="h-4 w-4" />
                      </Button>

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        disabled={page === 1}
                        className="h-11 rounded-full px-4"
                      >
                        <ChevronLeft className="h-4 w-4 sm:mr-1" />
                        <span className="hidden sm:inline">上一页</span>
                      </Button>

                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          value={jumpToPage}
                          onChange={(e) => setJumpToPage(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleJumpToPage()}
                          placeholder={page.toString()}
                          className="h-11 w-20 rounded-full border-0 bg-muted/70 text-center shadow-none focus-visible:ring-0"
                          min={1}
                          max={totalPages}
                        />
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleJumpToPage}
                          disabled={!jumpToPage}
                          className="h-11 rounded-full px-4"
                        >
                          跳转
                        </Button>
                      </div>

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPage((p) => p + 1)}
                        disabled={page >= totalPages}
                        className="h-11 rounded-full px-4"
                      >
                        <span className="hidden sm:inline">下一页</span>
                        <ChevronRight className="h-4 w-4 sm:ml-1" />
                      </Button>

                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => setPage(totalPages)}
                        disabled={page >= totalPages}
                        className="hidden h-11 w-11 rounded-full sm:inline-flex"
                      >
                        <ChevronsRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* 详情对话框 */}
          <EmojiDetailDialog
            emoji={selectedEmoji}
            open={detailDialogOpen}
            onOpenChange={setDetailDialogOpen}
          />

          {/* 编辑对话框 */}
          <EmojiEditDialog
            emoji={selectedEmoji}
            open={editDialogOpen}
            onOpenChange={setEditDialogOpen}
            onSuccess={() => {
              loadEmojiList()
              loadStats()
            }}
          />

          {/* 上传对话框 */}
          <EmojiUploadDialog
            open={uploadDialogOpen}
            onOpenChange={setUploadDialogOpen}
            onSuccess={() => {
              loadEmojiList()
              loadStats()
            }}
          />
        </div>
      </ScrollArea>

      {/* 批量删除确认对话框 */}
      <AlertDialog open={batchDeleteDialogOpen} onOpenChange={setBatchDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认批量删除</AlertDialogTitle>
            <AlertDialogDescription>
              你确定要删除选中的 {selectedIds.size} 个表情包吗？此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleBatchDelete}>确认删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 删除确认对话框 */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>确定要删除这个表情包吗？此操作无法撤销。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// 详情对话框组件
function EmojiDetailDialog({
  emoji,
  open,
  onOpenChange,
}: {
  emoji: Emoji | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  if (!emoji) return null

  const formatTime = (timestamp: number | null) => {
    if (!timestamp) return '-'
    return new Date(timestamp * 1000).toLocaleString('zh-CN')
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>表情包详情</DialogTitle>
        </DialogHeader>
        <ScrollArea className="max-h-[calc(90vh-8rem)] pr-4">
          <div className="space-y-4">
            {/* 表情包预览图 - 使用原图 */}
            <div className="flex justify-center">
              <div className="flex h-32 w-32 items-center justify-center overflow-hidden rounded-[24px] bg-muted/80 shadow-[0_1px_0_rgba(255,255,255,0.64)_inset,0_10px_24px_rgba(31,41,55,0.055)]">
                <img
                  src={getEmojiOriginalUrl(emoji.id)}
                  alt={emoji.description || '表情包'}
                  className="h-full w-full object-cover"
                  onError={(e) => {
                    const target = e.target as HTMLImageElement
                    target.style.display = 'none'
                    const parent = target.parentElement
                    if (parent) {
                      parent.innerHTML =
                        '<svg class="h-16 w-16 text-muted-foreground" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>'
                    }
                  }}
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="text-muted-foreground">ID</Label>
                <div className="mt-1 font-mono">{emoji.id}</div>
              </div>
              <div>
                <Label className="text-muted-foreground">格式</Label>
                <div className="mt-1">
                  <Badge variant="outline">{emoji.format.toUpperCase()}</Badge>
                </div>
              </div>
            </div>

            <div>
              <Label className="text-muted-foreground">文件路径</Label>
              <div className="mt-1 break-all rounded-[14px] bg-muted/35 p-3 font-mono text-sm">
                {emoji.full_path}
              </div>
            </div>

            <div>
              <Label className="text-muted-foreground">哈希值</Label>
              <div className="mt-1 break-all rounded-[14px] bg-muted/35 p-3 font-mono text-sm">
                {emoji.emoji_hash}
              </div>
            </div>

            <div>
              <Label className="text-muted-foreground">描述</Label>
              {emoji.description ? (
                <div className="mt-1 rounded-[14px] border border-black/[0.035] bg-muted/35 p-3 dark:border-white/10">
                  <Markdown className="prose-sm">{emoji.description}</Markdown>
                </div>
              ) : (
                <div className="mt-1 text-sm text-muted-foreground">-</div>
              )}
            </div>

            <div>
              <Label className="text-muted-foreground">情绪</Label>
              <div className="mt-1">
                {emoji.emotion ? (
                  <span className="text-sm">{emoji.emotion}</span>
                ) : (
                  <span className="text-sm text-muted-foreground">-</span>
                )}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="text-muted-foreground">状态</Label>
                <div className="mt-2 flex gap-2">
                  {emoji.is_registered && (
                    <Badge variant="secondary" className={softGreenBadgeClass}>
                      已注册
                    </Badge>
                  )}
                  {emoji.is_banned && (
                    <Badge variant="secondary" className={softRedBadgeClass}>
                      已封禁
                    </Badge>
                  )}
                  {!emoji.is_registered && !emoji.is_banned && (
                    <Badge variant="outline">未注册</Badge>
                  )}
                </div>
              </div>
              <div>
                <Label className="text-muted-foreground">使用次数</Label>
                <div className="mt-1 font-mono text-lg">{emoji.usage_count}</div>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="text-muted-foreground">记录时间</Label>
                <div className="mt-1 text-sm">{formatTime(emoji.record_time)}</div>
              </div>
              <div>
                <Label className="text-muted-foreground">注册时间</Label>
                <div className="mt-1 text-sm">{formatTime(emoji.register_time)}</div>
              </div>
            </div>

            <div>
              <Label className="text-muted-foreground">最后使用</Label>
              <div className="mt-1 text-sm">{formatTime(emoji.last_used_time)}</div>
            </div>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}

// 编辑对话框组件
function EmojiEditDialog({
  emoji,
  open,
  onOpenChange,
  onSuccess,
}: {
  emoji: Emoji | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: () => void
}) {
  const [emotionInput, setEmotionInput] = useState('')
  const [isRegistered, setIsRegistered] = useState(false)
  const [isBanned, setIsBanned] = useState(false)
  const [saving, setSaving] = useState(false)

  const { toast } = useToast()

  useEffect(() => {
    if (emoji) {
      setEmotionInput(emoji.emotion || '')
      setIsRegistered(emoji.is_registered)
      setIsBanned(emoji.is_banned)
    }
  }, [emoji])

  const handleSave = async () => {
    if (!emoji) return

    try {
      setSaving(true)
      // 将输入的标签字符串标准化为逗号分隔格式
      const emotionString = emotionInput
        .split(/[,,]/)
        .map((s) => s.trim())
        .filter(Boolean)
        .join(',')

      await updateEmoji(emoji.id, {
        emotion: emotionString || undefined,
        is_registered: isRegistered,
        is_banned: isBanned,
      })

      toast({
        title: '成功',
        description: '表情包信息已更新',
      })
      onOpenChange(false)
      onSuccess()
    } catch (error) {
      const message = error instanceof Error ? error.message : '保存失败'
      toast({
        title: '错误',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  if (!emoji) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>编辑表情包</DialogTitle>
          <DialogDescription>修改表情包的情绪和状态信息</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label>情绪</Label>
            <Textarea
              value={emotionInput}
              onChange={(e) => setEmotionInput(e.target.value)}
              placeholder="输入情绪描述..."
              rows={2}
              className="mt-1"
            />
            <p className="mt-1 text-xs text-muted-foreground">输入情绪相关的文本描述</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex items-center space-x-2">
              <Checkbox
                id="is_registered"
                checked={isRegistered}
                onCheckedChange={(checked) => {
                  if (checked === true) {
                    setIsRegistered(true)
                    setIsBanned(false) // 注册时自动取消封禁
                  } else {
                    setIsRegistered(false)
                  }
                }}
              />
              <Label htmlFor="is_registered" className="cursor-pointer">
                已注册
              </Label>
            </div>

            <div className="flex items-center space-x-2">
              <Checkbox
                id="is_banned"
                checked={isBanned}
                onCheckedChange={(checked) => {
                  if (checked === true) {
                    setIsBanned(true)
                    setIsRegistered(false) // 封禁时自动取消注册
                  } else {
                    setIsBanned(false)
                  }
                }}
              />
              <Label htmlFor="is_banned" className="cursor-pointer">
                已封禁
              </Label>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// 上传对话框组件
// 上传文件的元数据类型
interface UploadedFileInfo {
  id: string
  name: string
  previewUrl: string
  emotion: string
  description: string
  isRegistered: boolean
  file: File
}

// 上传步骤类型
type UploadStep = 'select' | 'edit-single' | 'edit-multiple'

function EmojiUploadDialog({
  open,
  onOpenChange,
  onSuccess,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: () => void
}) {
  const [step, setStep] = useState<UploadStep>('select')
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFileInfo[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const { toast } = useToast()

  // 创建 Uppy 实例（仅用于文件选择，不自动上传）
  const uppy = useMemo(() => {
    const uppyInstance = new Uppy({
      id: 'emoji-uploader',
      autoProceed: false,
      restrictions: {
        maxFileSize: 10 * 1024 * 1024, // 10MB
        allowedFileTypes: ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
        maxNumberOfFiles: 20,
      },
      locale: {
        pluralize: () => 0,
        strings: {
          addMoreFiles: '添加更多文件',
          addingMoreFiles: '正在添加更多文件',
          allowedFileTypes: '允许的文件类型：%{types}',
          cancel: '取消',
          closeModal: '关闭',
          complete: '完成',
          connectedToInternet: '已连接到互联网',
          copyLink: '复制链接',
          copyLinkToClipboardFallback: '复制下方链接',
          copyLinkToClipboardSuccess: '链接已复制到剪贴板',
          dashboardTitle: '选择文件',
          dashboardWindowTitle: '文件选择窗口（按 ESC 关闭）',
          done: '完成',
          dropHereOr: '拖放文件到这里或 %{browse}',
          dropHint: '将文件拖放到此处',
          dropPasteFiles: '将文件拖放到这里或 %{browseFiles}',
          dropPasteFolders: '将文件拖放到这里或 %{browseFolders}',
          dropPasteBoth: '将文件拖放到这里，%{browseFiles} 或 %{browseFolders}',
          dropPasteImportFiles: '将文件拖放到这里，%{browseFiles} 或从以下位置导入：',
          dropPasteImportFolders: '将文件拖放到这里，%{browseFolders} 或从以下位置导入：',
          dropPasteImportBoth:
            '将文件拖放到这里，%{browseFiles}，%{browseFolders} 或从以下位置导入：',
          editFile: '编辑文件',
          editing: '正在编辑 %{file}',
          emptyFolderAdded: '未从空文件夹添加文件',
          exceedsSize: '%{file} 超过了最大允许大小 %{size}',
          failedToUpload: '上传 %{file} 失败',
          fileSource: '文件来源：%{name}',
          filesUploadedOfTotal: {
            0: '已上传 %{complete} / %{smart_count} 个文件',
            1: '已上传 %{complete} / %{smart_count} 个文件',
          },
          filter: '筛选',
          finishEditingFile: '完成编辑文件',
          folderAdded: {
            0: '已从 %{folder} 添加 %{smart_count} 个文件',
            1: '已从 %{folder} 添加 %{smart_count} 个文件',
          },
          generatingThumbnails: '正在生成缩略图...',
          import: '导入',
          importFiles: '从以下位置导入文件：',
          importFrom: '从 %{name} 导入',
          loading: '加载中...',
          logOut: '登出',
          myDevice: '我的设备',
          noFilesFound: '这里没有文件或文件夹',
          noInternetConnection: '无网络连接',
          openFolderNamed: '打开文件夹 %{name}',
          pause: '暂停',
          pauseUpload: '暂停上传',
          paused: '已暂停',
          poweredBy: '技术支持：%{uppy}',
          processingXFiles: {
            0: '正在处理 %{smart_count} 个文件',
            1: '正在处理 %{smart_count} 个文件',
          },
          recording: '录制中',
          removeFile: '移除文件',
          resetFilter: '重置筛选',
          resume: '继续',
          resumeUpload: '继续上传',
          retry: '重试',
          retryUpload: '重试上传',
          save: '保存',
          saveChanges: '保存更改',
          selectFileNamed: '选择文件 %{name}',
          selectX: {
            0: '选择 %{smart_count}',
            1: '选择 %{smart_count}',
          },
          smile: '笑一个！',
          startRecording: '开始录制视频',
          stopRecording: '停止录制视频',
          takePicture: '拍照',
          timedOut: '上传已停滞 %{seconds} 秒，正在中止。',
          upload: '下一步',
          uploadComplete: '上传完成',
          uploadFailed: '上传失败',
          uploadPaused: '上传已暂停',
          uploadXFiles: {
            0: '下一步（%{smart_count} 个文件）',
            1: '下一步（%{smart_count} 个文件）',
          },
          uploadXNewFiles: {
            0: '下一步（+%{smart_count} 个文件）',
            1: '下一步（+%{smart_count} 个文件）',
          },
          uploading: '正在上传',
          uploadingXFiles: {
            0: '正在上传 %{smart_count} 个文件',
            1: '正在上传 %{smart_count} 个文件',
          },
          xFilesSelected: {
            0: '已选择 %{smart_count} 个文件',
            1: '已选择 %{smart_count} 个文件',
          },
          xMoreFilesAdded: {
            0: '又添加了 %{smart_count} 个文件',
            1: '又添加了 %{smart_count} 个文件',
          },
          xTimeLeft: '剩余 %{time}',
          youCanOnlyUploadFileTypes: '您只能上传：%{types}',
          youCanOnlyUploadX: {
            0: '您只能上传 %{smart_count} 个文件',
            1: '您只能上传 %{smart_count} 个文件',
          },
          youHaveToAtLeastSelectX: {
            0: '您至少需要选择 %{smart_count} 个文件',
            1: '您至少需要选择 %{smart_count} 个文件',
          },
          browseFiles: '浏览文件',
          browseFolders: '浏览文件夹',
          cancelUpload: '取消上传',
          addMore: '添加更多',
          back: '返回',
          editFileWithFilename: '编辑文件 %{file}',
        },
      },
    })

    return uppyInstance
  }, [])

  // 处理"下一步"按钮点击 - 进入编辑阶段
  useEffect(() => {
    const handleUpload = () => {
      const files = uppy.getFiles()
      if (files.length === 0) return

      // 将选择的文件转换为我们的数据结构
      const fileInfos: UploadedFileInfo[] = files.map((file) => ({
        id: file.id,
        name: file.name,
        previewUrl: file.preview || URL.createObjectURL(file.data as File),
        emotion: '',
        description: '',
        isRegistered: true,
        file: file.data as File,
      }))

      setUploadedFiles(fileInfos)

      // 根据文件数量决定进入哪个步骤
      if (files.length === 1) {
        setSelectedFileId(fileInfos[0].id)
        setStep('edit-single')
      } else {
        setStep('edit-multiple')
      }
    }

    uppy.on('upload', handleUpload)
    return () => {
      uppy.off('upload', handleUpload)
    }
  }, [uppy])

  // 对话框关闭时重置状态
  useEffect(() => {
    if (!open) {
      uppy.cancelAll()
      setStep('select')
      setUploadedFiles([])
      setSelectedFileId(null)
      setUploading(false)
    }
  }, [open, uppy])

  // 更新单个文件的元数据
  const updateFileInfo = useCallback((fileId: string, updates: Partial<UploadedFileInfo>) => {
    setUploadedFiles((prev) => prev.map((f) => (f.id === fileId ? { ...f, ...updates } : f)))
  }, [])

  // 检查文件是否填写完成必填项（情感标签必填）
  const isFileComplete = useCallback((file: UploadedFileInfo) => {
    return file.emotion.trim().length > 0
  }, [])

  // 检查所有文件是否都填写完成
  const allFilesComplete = useMemo(() => {
    return uploadedFiles.length > 0 && uploadedFiles.every(isFileComplete)
  }, [uploadedFiles, isFileComplete])

  // 获取当前选中的文件
  const selectedFile = useMemo(() => {
    return uploadedFiles.find((f) => f.id === selectedFileId) || null
  }, [uploadedFiles, selectedFileId])

  // 返回上一步
  const handleBack = useCallback(() => {
    if (step === 'edit-single' || step === 'edit-multiple') {
      setStep('select')
      setUploadedFiles([])
      setSelectedFileId(null)
    }
  }, [step])

  // 执行实际上传
  const handleSubmit = useCallback(async () => {
    if (!allFilesComplete) {
      toast({
        title: '请填写必填项',
        description: '每个表情包的情感标签都是必填的',
        variant: 'destructive',
      })
      return
    }

    setUploading(true)
    let successCount = 0
    let failedCount = 0

    try {
      for (const fileInfo of uploadedFiles) {
        const formData = new FormData()
        formData.append('file', fileInfo.file)
        formData.append('emotion', fileInfo.emotion)
        formData.append('description', fileInfo.description)
        formData.append('is_registered', fileInfo.isRegistered.toString())

        try {
          const response = await fetch(getEmojiUploadUrl(), {
            method: 'POST',
            credentials: 'include',
            body: formData,
          })

          if (response.ok) {
            successCount++
          } else {
            failedCount++
          }
        } catch {
          failedCount++
        }
      }

      if (failedCount === 0) {
        toast({
          title: '上传成功',
          description: `成功上传 ${successCount} 个表情包`,
        })
        onOpenChange(false)
        onSuccess()
      } else {
        toast({
          title: '部分上传失败',
          description: `成功 ${successCount} 个，失败 ${failedCount} 个`,
          variant: 'destructive',
        })
        onSuccess()
      }
    } finally {
      setUploading(false)
    }
  }, [allFilesComplete, uploadedFiles, toast, onOpenChange, onSuccess])

  // 渲染文件选择步骤
  const renderSelectStep = () => (
    <div className="space-y-4">
      <div className="w-full overflow-hidden rounded-[18px] border border-black/[0.035] bg-white/[0.78] shadow-[0_1px_0_rgba(255,255,255,0.72)_inset,0_10px_26px_rgba(31,41,55,0.045)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.09]">
        <Dashboard
          uppy={uppy}
          proudlyDisplayPoweredByUppy={false}
          hideProgressDetails
          height={350}
          width="100%"
          theme="auto"
          note="支持 JPG、PNG、GIF、WebP 格式，最多 20 个文件"
        />
      </div>
    </div>
  )

  // 渲染单个文件编辑步骤
  const renderEditSingleStep = () => {
    const file = uploadedFiles[0]
    if (!file) return null

    return (
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="ghost" size="sm" onClick={handleBack}>
            <ArrowLeft className="mr-1 h-4 w-4" />
            返回
          </Button>
          <span className="text-sm text-muted-foreground">编辑表情包信息</span>
        </div>

        <div className="flex flex-col gap-5 sm:flex-row sm:gap-6">
          {/* 预览图 */}
          <div className="flex-shrink-0 sm:w-36">
            <div className="mx-auto flex h-36 w-36 items-center justify-center overflow-hidden rounded-[22px] border border-black/[0.035] bg-secondary/55 shadow-[0_1px_0_rgba(255,255,255,0.72)_inset,0_10px_26px_rgba(31,41,55,0.055)] dark:border-white/10">
              <img
                src={file.previewUrl}
                alt={file.name}
                className="max-h-full max-w-full object-contain"
              />
            </div>
            <p className="mx-auto mt-2 max-w-36 truncate text-center text-xs text-muted-foreground">
              {file.name}
            </p>
          </div>

          {/* 表单 */}
          <div className="flex-1 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="single-emotion">
                情感标签 <span className="text-destructive">*</span>
              </Label>
              <Input
                id="single-emotion"
                value={file.emotion}
                onChange={(e) => updateFileInfo(file.id, { emotion: e.target.value })}
                placeholder="多个标签用逗号分隔，如：开心,高兴"
                className={!file.emotion.trim() ? 'border-destructive' : ''}
              />
              <p className="text-xs text-muted-foreground">用于情感匹配，多个标签用逗号分隔</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="single-description">描述</Label>
              <Input
                id="single-description"
                value={file.description}
                onChange={(e) => updateFileInfo(file.id, { description: e.target.value })}
                placeholder="输入表情包描述..."
              />
            </div>

            <label
              htmlFor="single-is-registered"
              className="ios-touch flex min-h-[52px] cursor-pointer items-center gap-3 rounded-[16px] bg-secondary/50 px-3 py-2"
            >
              <Checkbox
                id="single-is-registered"
                checked={file.isRegistered}
                onCheckedChange={(checked) =>
                  updateFileInfo(file.id, { isRegistered: checked === true })
                }
              />
              <span className="text-[15px] leading-5 text-foreground">
                上传后立即注册（可被当前实例使用）
              </span>
            </label>
          </div>
        </div>

        <DialogFooter>
          <Button onClick={handleSubmit} disabled={!allFilesComplete || uploading}>
            {uploading ? '上传中...' : '上传'}
          </Button>
        </DialogFooter>
      </div>
    )
  }

  // 渲染多个文件编辑步骤
  const renderEditMultipleStep = () => {
    const completedCount = uploadedFiles.filter(isFileComplete).length
    const totalCount = uploadedFiles.length

    return (
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <Button variant="ghost" size="sm" onClick={handleBack}>
              <ArrowLeft className="mr-1 h-4 w-4" />
              返回
            </Button>
            <span className="text-sm text-muted-foreground">
              编辑表情包信息（{completedCount}/{totalCount} 已完成）
            </span>
          </div>
          <Badge variant={allFilesComplete ? 'default' : 'secondary'}>
            {allFilesComplete ? (
              <>
                <Check className="mr-1 h-3 w-3" />
                全部完成
              </>
            ) : (
              <>
                <X className="mr-1 h-3 w-3" />
                未完成
              </>
            )}
          </Badge>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          {/* 左侧：文件卡片列表 */}
          <ScrollArea className="h-[320px] pr-2 sm:h-[350px]">
            <div className="space-y-2">
              {uploadedFiles.map((file) => {
                const complete = isFileComplete(file)
                const isSelected = selectedFileId === file.id
                return (
                  <div
                    key={file.id}
                    onClick={() => setSelectedFileId(file.id)}
                    className={cn(
                      'ios-touch flex min-h-[72px] cursor-pointer items-center gap-3 rounded-[17px] border border-black/[0.035] bg-card p-3 shadow-[0_1px_0_rgba(255,255,255,0.72)_inset,0_6px_18px_rgba(31,41,55,0.04)] transition-all dark:border-white/10 dark:bg-card',
                      isSelected && 'ring-2 ring-primary/70',
                      complete
                        ? 'border-[rgb(52_199_89_/_0.22)] bg-[rgb(52_199_89_/_0.08)] dark:bg-[rgb(48_209_88_/_0.1)]'
                        : 'hover:bg-muted/35'
                    )}
                  >
                    <div className="flex h-14 w-14 flex-shrink-0 items-center justify-center overflow-hidden rounded-[15px] border border-black/[0.035] bg-secondary/55 dark:border-white/10">
                      <img
                        src={file.previewUrl}
                        alt={file.name}
                        className="max-h-full max-w-full object-contain"
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{file.name}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {file.emotion || '未填写情感标签'}
                      </p>
                    </div>
                    {complete ? (
                      <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]" />
                    ) : (
                      <div className="h-5 w-5 flex-shrink-0 rounded-full border-2 border-muted-foreground/30" />
                    )}
                  </div>
                )
              })}
            </div>
          </ScrollArea>

          {/* 右侧：选中文件的编辑表单 */}
          <div className="rounded-[20px] border border-black/[0.035] bg-card p-4 shadow-[0_1px_0_rgba(255,255,255,0.72)_inset,0_10px_26px_rgba(31,41,55,0.045)] dark:border-white/10 dark:bg-card">
            {selectedFile ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-[17px] border border-black/[0.035] bg-secondary/55 dark:border-white/10">
                    <img
                      src={selectedFile.previewUrl}
                      alt={selectedFile.name}
                      className="max-h-full max-w-full object-contain"
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{selectedFile.name}</p>
                    {isFileComplete(selectedFile) && (
                      <Badge variant="secondary" className={softGreenBadgeClass}>
                        <Check className="mr-1 h-3 w-3" />
                        已完成
                      </Badge>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="multi-emotion">
                    情感标签 <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="multi-emotion"
                    value={selectedFile.emotion}
                    onChange={(e) => updateFileInfo(selectedFile.id, { emotion: e.target.value })}
                    placeholder="多个标签用逗号分隔，如：开心,高兴"
                    className={!selectedFile.emotion.trim() ? 'border-destructive' : ''}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="multi-description">描述</Label>
                  <Input
                    id="multi-description"
                    value={selectedFile.description}
                    onChange={(e) =>
                      updateFileInfo(selectedFile.id, { description: e.target.value })
                    }
                    placeholder="输入表情包描述..."
                  />
                </div>

                <label
                  htmlFor="multi-is-registered"
                  className="ios-touch flex min-h-[52px] cursor-pointer items-center gap-3 rounded-[16px] bg-secondary/50 px-3 py-2"
                >
                  <Checkbox
                    id="multi-is-registered"
                    checked={selectedFile.isRegistered}
                    onCheckedChange={(checked) =>
                      updateFileInfo(selectedFile.id, { isRegistered: checked === true })
                    }
                  />
                  <span className="text-[15px] leading-5 text-foreground">上传后立即注册</span>
                </label>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-muted-foreground">
                <div className="text-center">
                  <ImageIcon className="mx-auto mb-2 h-12 w-12 opacity-50" />
                  <p>点击左侧卡片编辑</p>
                </div>
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button onClick={handleSubmit} disabled={!allFilesComplete || uploading}>
            {uploading ? '上传中...' : `上传全部 (${totalCount})`}
          </Button>
        </DialogFooter>
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-hidden sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            {step === 'select' && '上传表情包 - 选择文件'}
            {step === 'edit-single' && '上传表情包 - 填写信息'}
            {step === 'edit-multiple' && '上传表情包 - 批量编辑'}
          </DialogTitle>
          <DialogDescription>
            {step === 'select' &&
              '支持 JPG、PNG、GIF、WebP 格式，单个文件最大 10MB，可同时上传多个文件'}
            {step === 'edit-single' && '请填写表情包的情感标签（必填）和描述'}
            {step === 'edit-multiple' && '点击左侧卡片编辑每个表情包的信息，情感标签为必填项'}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[calc(90vh-8rem)] overflow-y-auto pr-1">
          {step === 'select' && renderSelectStep()}
          {step === 'edit-single' && renderEditSingleStep()}
          {step === 'edit-multiple' && renderEditMultipleStep()}
        </div>
      </DialogContent>
    </Dialog>
  )
}
