import {
  Hash,
  Search,
  Edit,
  Trash2,
  Eye,
  Plus,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Check,
  X,
  HelpCircle,
  Globe,
  MessageCircle,
  SlidersHorizontal,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { MarkdownRenderer } from '@/components/markdown-renderer'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { Switch } from '@/components/ui/switch'
import { IosListSkeleton } from '@/components/ui/skeleton'
import type {
  Jargon,
  JargonCreateRequest,
  JargonUpdateRequest,
  JargonChatInfo,
  JargonStats,
} from '@/types/jargon'
import {
  getJargonList,
  getJargonDetail,
  createJargon,
  updateJargon,
  deleteJargon,
  batchDeleteJargons,
  getJargonStats,
  getJargonChatList,
  batchSetJargonStatus,
} from '@/lib/jargon-api'

const JARGON_STATUS_OPTIONS = [
  { value: 'all', label: '全部状态', description: '不限判定状态' },
  { value: 'true', label: '是黑话', description: '只看已确认黑话' },
  { value: 'false', label: '非黑话', description: '只看确认非黑话' },
  { value: 'null', label: '未判定', description: '只看待判定词条' },
] as const

const softGreenBadgeClass =
  'border-0 bg-[rgb(52_199_89_/_0.13)] text-[rgb(36_138_61)] shadow-[0_1px_0_rgba(255,255,255,0.5)_inset] dark:text-[rgb(48_209_88)]'

export function JargonManagementPage() {
  const [jargons, setJargons] = useState<Jargon[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [filterChatId, setFilterChatId] = useState<string>('all')
  const [filterIsJargon, setFilterIsJargon] = useState<string>('all')
  const [selectedJargon, setSelectedJargon] = useState<Jargon | null>(null)
  const [isDetailDialogOpen, setIsDetailDialogOpen] = useState(false)
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [deleteConfirmJargon, setDeleteConfirmJargon] = useState<Jargon | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [isBatchDeleteDialogOpen, setIsBatchDeleteDialogOpen] = useState(false)
  const [jumpToPage, setJumpToPage] = useState('')
  const [stats, setStats] = useState<JargonStats>({
    total: 0,
    confirmed_jargon: 0,
    confirmed_not_jargon: 0,
    pending: 0,
    global_count: 0,
    complete_count: 0,
    chat_count: 0,
    top_chats: {},
  })
  const [chatList, setChatList] = useState<JargonChatInfo[]>([])
  const { toast } = useToast()

  // 加载黑话列表
  const loadJargons = async () => {
    try {
      setLoading(true)
      const response = await getJargonList({
        page,
        page_size: pageSize,
        search: search || undefined,
        chat_id: filterChatId === 'all' ? undefined : filterChatId,
        is_jargon:
          filterIsJargon === 'all'
            ? undefined
            : filterIsJargon === 'true'
              ? true
              : filterIsJargon === 'false'
                ? false
                : undefined,
      })
      setJargons(response.data)
      setTotal(response.total)
    } catch (error) {
      toast({
        title: '加载失败',
        description: error instanceof Error ? error.message : '无法加载黑话列表',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }

  // 加载统计数据
  const loadStats = async () => {
    try {
      const response = await getJargonStats()
      if (response?.data) {
        setStats(response.data)
      }
    } catch (error) {
      console.error('加载统计数据失败:', error)
    }
  }

  // 加载聊天列表
  const loadChatList = async () => {
    try {
      const response = await getJargonChatList()
      if (response?.data) {
        setChatList(response.data)
      }
    } catch (error) {
      console.error('加载聊天列表失败:', error)
    }
  }

  // 初始加载
  useEffect(() => {
    loadJargons()
    loadStats()
    loadChatList()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, filterChatId, filterIsJargon])

  // 查看详情
  const handleViewDetail = async (jargon: Jargon) => {
    try {
      const response = await getJargonDetail(jargon.id)
      setSelectedJargon(response.data)
      setIsDetailDialogOpen(true)
    } catch (error) {
      toast({
        title: '加载详情失败',
        description: error instanceof Error ? error.message : '无法加载黑话详情',
        variant: 'destructive',
      })
    }
  }

  // 编辑黑话
  const handleEdit = (jargon: Jargon) => {
    setSelectedJargon(jargon)
    setIsEditDialogOpen(true)
  }

  // 删除黑话
  const handleDelete = async (jargon: Jargon) => {
    try {
      await deleteJargon(jargon.id)
      toast({
        title: '删除成功',
        description: `已删除黑话: ${jargon.content}`,
      })
      setDeleteConfirmJargon(null)
      loadJargons()
      loadStats()
    } catch (error) {
      toast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '无法删除黑话',
        variant: 'destructive',
      })
    }
  }

  // 切换单个选择
  const toggleSelect = (id: number) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelectedIds(newSelected)
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedIds.size === jargons.length && jargons.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(jargons.map((j) => j.id)))
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    try {
      await batchDeleteJargons(Array.from(selectedIds))
      toast({
        title: '批量删除成功',
        description: `已删除 ${selectedIds.size} 个黑话`,
      })
      setSelectedIds(new Set())
      setIsBatchDeleteDialogOpen(false)
      loadJargons()
      loadStats()
    } catch (error) {
      toast({
        title: '批量删除失败',
        description: error instanceof Error ? error.message : '无法批量删除黑话',
        variant: 'destructive',
      })
    }
  }

  // 批量设置为黑话
  const handleBatchSetJargon = async (isJargon: boolean) => {
    try {
      await batchSetJargonStatus(Array.from(selectedIds), isJargon)
      toast({
        title: '操作成功',
        description: `已将 ${selectedIds.size} 个词条设为${isJargon ? '黑话' : '非黑话'}`,
      })
      setSelectedIds(new Set())
      loadJargons()
      loadStats()
    } catch (error) {
      toast({
        title: '操作失败',
        description: error instanceof Error ? error.message : '批量设置失败',
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
  const jargonStatItems = [
    {
      label: '总数量',
      value: stats.total,
      detail: '全部词条',
      Icon: Hash,
      symbolClassName: 'ios-symbol-pink',
    },
    {
      label: '已确认黑话',
      value: stats.confirmed_jargon,
      detail: '可用词条',
      Icon: Check,
      symbolClassName: 'ios-symbol-green',
    },
    {
      label: '确认非黑话',
      value: stats.confirmed_not_jargon,
      detail: '已排除',
      Icon: X,
      symbolClassName: 'ios-symbol-gray',
    },
    {
      label: '待判定',
      value: stats.pending,
      detail: '需要确认',
      Icon: HelpCircle,
      symbolClassName: 'ios-symbol-orange',
    },
    {
      label: '全局黑话',
      value: stats.global_count,
      detail: '全局生效',
      Icon: Globe,
      symbolClassName: 'ios-symbol-purple',
    },
    {
      label: '推断完成',
      value: stats.complete_count,
      detail: '已处理',
      Icon: Check,
      symbolClassName: 'ios-symbol-blue',
    },
    {
      label: '关联聊天数',
      value: stats.chat_count,
      detail: '覆盖范围',
      Icon: MessageCircle,
      symbolClassName: 'ios-symbol-teal',
    },
  ]

  // 渲染黑话状态徽章
  const renderJargonStatus = (isJargon: boolean | null) => {
    if (isJargon === true) {
      return (
        <Badge variant="secondary" className={softGreenBadgeClass}>
          <Check className="mr-1 h-3 w-3" />
          是黑话
        </Badge>
      )
    } else if (isJargon === false) {
      return (
        <Badge variant="secondary">
          <X className="mr-1 h-3 w-3" />
          非黑话
        </Badge>
      )
    } else {
      return (
        <Badge variant="outline">
          <HelpCircle className="mr-1 h-3 w-3" />
          未判定
        </Badge>
      )
    }
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col px-5 py-5 sm:p-6">
      {/* 页面标题 */}
      <div className="mb-4 sm:mb-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">黑话管理</h1>
            <p className="ios-subtitle">管理当前实例学习到的黑话和俚语</p>
          </div>
          <Button
            onClick={() => setIsCreateDialogOpen(true)}
            className="hidden gap-2 sm:inline-flex"
          >
            <Plus className="h-4 w-4" />
            新增黑话
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-4 sm:space-y-6 sm:pr-4">
          <button
            type="button"
            onClick={() => setIsCreateDialogOpen(true)}
            className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                <Plus className="h-4 w-4" />
              </span>
              <span className="block min-w-0 truncate text-[16px] font-normal leading-6">
                新增黑话
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>

          {/* 统计 */}
          <div className="ios-stat-grid">
            {jargonStatItems.map(({ label, value, detail, Icon, symbolClassName }) => (
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

          <div className="ios-search-field">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="search"
              placeholder="搜索内容或含义"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              className="ios-search-input"
            />
          </div>

          {/* 筛选 */}
          <div className="ios-group overflow-hidden">
            <div className="ios-row min-h-[64px]">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                  <MessageCircle className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">聊天筛选</span>
                </span>
              </span>
              <Select
                value={filterChatId}
                onValueChange={(value) => {
                  setFilterChatId(value)
                  setPage(1)
                }}
              >
                <SelectTrigger className="h-auto min-h-0 w-auto max-w-[11rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                  <SelectValue placeholder="全部聊天" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部聊天</SelectItem>
                  {chatList.map((chat) => (
                    <SelectItem key={chat.chat_id} value={chat.chat_id}>
                      {chat.chat_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[64px]">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-pink">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">状态筛选</span>
                </span>
              </span>
              <Select
                value={filterIsJargon}
                onValueChange={(value) => {
                  setFilterIsJargon(value)
                  setPage(1)
                }}
              >
                <SelectTrigger className="h-auto min-h-0 w-auto max-w-[9rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                  <SelectValue placeholder="全部状态" />
                </SelectTrigger>
                <SelectContent>
                  {JARGON_STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div
              className={cn(
                'ios-row min-h-[64px]',
                selectedIds.size > 0 &&
                  'flex-col !items-stretch !justify-start gap-3 sm:flex-row sm:!items-center sm:!justify-between'
              )}
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">显示设置</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    已选 {selectedIds.size}
                  </span>
                </span>
              </span>
              <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
                <Select
                  value={pageSize.toString()}
                  onValueChange={(value) => {
                    setPageSize(parseInt(value))
                    setPage(1)
                    setSelectedIds(new Set())
                  }}
                >
                  <SelectTrigger
                    id="page-size"
                    className="h-auto min-h-0 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>svg]:h-4 [&>svg]:w-4"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="10">10 条</SelectItem>
                    <SelectItem value="20">20 条</SelectItem>
                    <SelectItem value="50">50 条</SelectItem>
                    <SelectItem value="100">100 条</SelectItem>
                  </SelectContent>
                </Select>
                {selectedIds.size > 0 && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleBatchSetJargon(true)}
                      className="h-10 rounded-full px-4"
                    >
                      <Check className="mr-1 h-4 w-4" />
                      黑话
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleBatchSetJargon(false)}
                      className="h-10 rounded-full px-4"
                    >
                      <X className="mr-1 h-4 w-4" />
                      非黑话
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedIds(new Set())}
                      className="h-10 rounded-full px-4"
                    >
                      取消选择
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => setIsBatchDeleteDialogOpen(true)}
                      className="h-10 rounded-full px-4"
                    >
                      <Trash2 className="mr-1 h-4 w-4" />
                      批量删除
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* 黑话列表 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">黑话列表</p>
              {jargons.length > 0 && (
                <button
                  type="button"
                  onClick={toggleSelectAll}
                  className="ios-touch rounded-full px-2.5 py-1 text-[13px] font-medium leading-5 text-primary hover:bg-accent/60"
                >
                  {selectedIds.size === jargons.length ? '取消全选' : '全选'}
                </button>
              )}
            </div>
            <div className="ios-group overflow-hidden">
              {loading ? (
                <IosListSkeleton rows={4} />
              ) : jargons.length === 0 ? (
                <div className="ios-empty-state">
                  <span className="ios-empty-illustration">
                    <Hash className="relative z-10 h-7 w-7 text-primary" />
                  </span>
                  <div>
                    <p className="text-[16px] font-semibold leading-6 text-foreground">暂无黑话</p>
                    <p className="mt-1 max-w-sm text-[13px] leading-5">
                      新增词条后，可以在这里判定状态、管理含义和关联聊天。
                    </p>
                  </div>
                  <Button
                    onClick={() => setIsCreateDialogOpen(true)}
                    size="sm"
                    className="h-9 px-4"
                  >
                    <Plus className="mr-1 h-4 w-4" />
                    新增黑话
                  </Button>
                </div>
              ) : (
                jargons.map((jargon) => (
                  <div
                    key={jargon.id}
                    className="ios-row min-h-[96px] flex-col !items-stretch !justify-start gap-3 py-3 sm:flex-row sm:!items-center sm:!justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <Checkbox
                        checked={selectedIds.has(jargon.id)}
                        onCheckedChange={() => toggleSelect(jargon.id)}
                        className="mt-2"
                      />
                      <span className="ios-symbol ios-symbol-sm ios-symbol-pink mt-0.5">
                        {jargon.is_global ? (
                          <Globe className="h-4 w-4" />
                        ) : (
                          <Hash className="h-4 w-4" />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <h3
                          className="line-clamp-1 text-[15px] font-semibold leading-5 text-foreground"
                          title={jargon.content}
                        >
                          {jargon.content}
                        </h3>
                        <p
                          className="mt-1 line-clamp-2 text-[13px] leading-5 text-muted-foreground"
                          title={jargon.meaning || ''}
                        >
                          {jargon.meaning || '暂无含义'}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          {renderJargonStatus(jargon.is_jargon)}
                          <span className="rounded-full bg-muted px-2.5 py-1 text-[12px] font-medium leading-4 text-muted-foreground">
                            {jargon.count} 次
                          </span>
                          <span
                            className="max-w-[12rem] truncate rounded-full bg-muted px-2.5 py-1 text-[12px] font-medium leading-4 text-muted-foreground"
                            title={jargon.chat_name || jargon.chat_id}
                          >
                            {jargon.chat_name || jargon.chat_id}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-2 pl-14 sm:pl-0">
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => handleEdit(jargon)}
                        className="h-9 rounded-full px-4"
                      >
                        <Edit className="mr-1 h-4 w-4" />
                        编辑
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        className="h-9 w-9 rounded-full"
                        onClick={() => handleViewDetail(jargon)}
                        title="查看详情"
                      >
                        <Eye className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setDeleteConfirmJargon(jargon)}
                        className="text-destructive hover:text-destructive h-9 rounded-full px-4"
                      >
                        <Trash2 className="mr-1 h-4 w-4" />
                        删除
                      </Button>
                    </div>
                  </div>
                ))
              )}

              {total > 0 && (
                <div className="ios-row ios-row-plain min-h-[68px] flex-col !items-stretch !justify-start gap-3 border-t border-border/60 sm:flex-row sm:!items-center sm:!justify-between">
                  <div className="text-sm text-muted-foreground">
                    共 {total} 条记录，第 {page} / {Math.ceil(total / pageSize)} 页
                  </div>
                  <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setPage(1)}
                      disabled={page === 1}
                      className="hidden h-9 w-9 rounded-full sm:inline-flex"
                    >
                      <ChevronsLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage(page - 1)}
                      disabled={page === 1}
                      className="h-9 rounded-full px-3"
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
                        className="h-9 w-16 rounded-full border-0 bg-muted/70 text-center shadow-none focus-visible:ring-0"
                        min={1}
                        max={Math.ceil(total / pageSize)}
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleJumpToPage}
                        disabled={!jumpToPage}
                        className="h-9 rounded-full px-3"
                      >
                        跳转
                      </Button>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage(page + 1)}
                      disabled={page >= Math.ceil(total / pageSize)}
                      className="h-9 rounded-full px-3"
                    >
                      <span className="hidden sm:inline">下一页</span>
                      <ChevronRight className="h-4 w-4 sm:ml-1" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setPage(Math.ceil(total / pageSize))}
                      disabled={page >= Math.ceil(total / pageSize)}
                      className="hidden h-9 w-9 rounded-full sm:inline-flex"
                    >
                      <ChevronsRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </ScrollArea>

      {/* 详情对话框 */}
      <JargonDetailDialog
        jargon={selectedJargon}
        open={isDetailDialogOpen}
        onOpenChange={setIsDetailDialogOpen}
      />

      {/* 创建对话框 */}
      <JargonCreateDialog
        open={isCreateDialogOpen}
        onOpenChange={setIsCreateDialogOpen}
        chatList={chatList}
        onSuccess={() => {
          loadJargons()
          loadStats()
          setIsCreateDialogOpen(false)
        }}
      />

      {/* 编辑对话框 */}
      <JargonEditDialog
        jargon={selectedJargon}
        open={isEditDialogOpen}
        onOpenChange={setIsEditDialogOpen}
        chatList={chatList}
        onSuccess={() => {
          loadJargons()
          loadStats()
          setIsEditDialogOpen(false)
        }}
      />

      {/* 删除确认对话框 */}
      <AlertDialog open={!!deleteConfirmJargon} onOpenChange={() => setDeleteConfirmJargon(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除黑话 "{deleteConfirmJargon?.content}" 吗？此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirmJargon && handleDelete(deleteConfirmJargon)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 批量删除确认对话框 */}
      <AlertDialog open={isBatchDeleteDialogOpen} onOpenChange={setIsBatchDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认批量删除</AlertDialogTitle>
            <AlertDialogDescription>
              您即将删除 {selectedIds.size} 个黑话，此操作无法撤销。确定要继续吗？
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleBatchDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// 黑话详情对话框
function JargonDetailDialog({
  jargon,
  open,
  onOpenChange,
}: {
  jargon: Jargon | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  if (!jargon) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="grid max-h-[80vh] max-w-2xl grid-rows-[auto_1fr_auto] overflow-hidden">
        <DialogHeader>
          <DialogTitle>黑话详情</DialogTitle>
          <DialogDescription>查看黑话的完整信息</DialogDescription>
        </DialogHeader>

        <ScrollArea className="h-full pr-4">
          <div className="space-y-4 pb-2">
            <div className="grid grid-cols-2 gap-4">
              <InfoItem icon={Hash} label="记录ID" value={jargon.id.toString()} mono />
              <InfoItem label="使用次数" value={jargon.count.toString()} />
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">内容</Label>
              <div className="whitespace-pre-wrap break-all rounded-[14px] bg-muted/35 p-3 text-sm leading-relaxed">
                {jargon.content}
              </div>
            </div>

            {jargon.raw_content && (
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">原始内容</Label>
                <div className="break-all rounded-[14px] bg-muted/35 p-3 text-sm leading-relaxed">
                  {(() => {
                    try {
                      const rawArray = JSON.parse(jargon.raw_content)
                      if (Array.isArray(rawArray)) {
                        return rawArray.map((item, index) => (
                          <div key={index}>
                            {index > 0 && <hr className="my-3 border-border" />}
                            <div className="whitespace-pre-wrap">{item}</div>
                          </div>
                        ))
                      }
                      return <div className="whitespace-pre-wrap">{jargon.raw_content}</div>
                    } catch {
                      return <div className="whitespace-pre-wrap">{jargon.raw_content}</div>
                    }
                  })()}
                </div>
              </div>
            )}

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">含义</Label>
              <div className="break-all rounded-[14px] bg-muted/35 p-3 text-sm leading-relaxed">
                {jargon.meaning ? <MarkdownRenderer content={jargon.meaning} /> : '-'}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <InfoItem label="聊天" value={jargon.chat_name || jargon.chat_id} />
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">状态</Label>
                <div className="flex items-center gap-2">
                  {jargon.is_jargon === true && (
                    <Badge variant="secondary" className={softGreenBadgeClass}>
                      是黑话
                    </Badge>
                  )}
                  {jargon.is_jargon === false && <Badge variant="secondary">非黑话</Badge>}
                  {jargon.is_jargon === null && <Badge variant="outline">未判定</Badge>}
                  {jargon.is_global && (
                    <Badge
                      variant="outline"
                      className="border-[rgb(0_122_255_/_0.22)] bg-[rgb(0_122_255_/_0.07)] text-[rgb(0_122_255)] dark:border-[rgb(10_132_255_/_0.28)] dark:bg-[rgb(10_132_255_/_0.12)] dark:text-[rgb(10_132_255)]"
                    >
                      全局
                    </Badge>
                  )}
                  {jargon.is_complete && (
                    <Badge
                      variant="outline"
                      className="border-[rgb(88_86_214_/_0.22)] bg-[rgb(88_86_214_/_0.07)] text-[rgb(88_86_214)] dark:border-[rgb(94_92_230_/_0.28)] dark:bg-[rgb(94_92_230_/_0.12)] dark:text-[rgb(94_92_230)]"
                    >
                      推断完成
                    </Badge>
                  )}
                </div>
              </div>
            </div>

            {jargon.inference_with_context && (
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">上下文推断结果</Label>
                <div className="max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-[14px] bg-muted/35 p-3 font-mono text-xs leading-relaxed">
                  {jargon.inference_with_context}
                </div>
              </div>
            )}

            {jargon.inference_content_only && (
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">纯词条推断结果</Label>
                <div className="max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all rounded-[14px] bg-muted/35 p-3 font-mono text-xs leading-relaxed">
                  {jargon.inference_content_only}
                </div>
              </div>
            )}
          </div>
        </ScrollArea>

        <DialogFooter className="flex-shrink-0">
          <Button onClick={() => onOpenChange(false)}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// 信息项组件
function InfoItem({
  icon: Icon,
  label,
  value,
  mono = false,
}: {
  icon?: typeof Hash
  label: string
  value: string | null | undefined
  mono?: boolean
}) {
  return (
    <div className="space-y-1">
      <Label className="flex items-center gap-1 text-xs text-muted-foreground">
        {Icon && <Icon className="h-3 w-3" />}
        {label}
      </Label>
      <div className={cn('text-sm', mono && 'font-mono', !value && 'text-muted-foreground')}>
        {value || '-'}
      </div>
    </div>
  )
}

// 黑话创建对话框
function JargonCreateDialog({
  open,
  onOpenChange,
  chatList,
  onSuccess,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  chatList: JargonChatInfo[]
  onSuccess: () => void
}) {
  const [formData, setFormData] = useState<JargonCreateRequest>({
    content: '',
    meaning: '',
    chat_id: '',
    is_global: false,
  })
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  const handleCreate = async () => {
    if (!formData.content || !formData.chat_id) {
      toast({
        title: '验证失败',
        description: '请填写必填字段：内容和聊天',
        variant: 'destructive',
      })
      return
    }

    try {
      setSaving(true)
      await createJargon(formData)
      toast({
        title: '创建成功',
        description: '黑话已创建',
      })
      setFormData({ content: '', meaning: '', chat_id: '', is_global: false })
      onSuccess()
    } catch (error) {
      toast({
        title: '创建失败',
        description: error instanceof Error ? error.message : '无法创建黑话',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>新增黑话</DialogTitle>
          <DialogDescription>创建新的黑话记录</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="content">
              内容 <span className="text-destructive">*</span>
            </Label>
            <Input
              id="content"
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              placeholder="输入黑话内容"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="meaning">含义</Label>
            <Textarea
              id="meaning"
              value={formData.meaning || ''}
              onChange={(e) => setFormData({ ...formData, meaning: e.target.value })}
              placeholder="输入黑话含义（可选）"
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="chat_id">
              聊天 <span className="text-destructive">*</span>
            </Label>
            <Select
              value={formData.chat_id}
              onValueChange={(value) => setFormData({ ...formData, chat_id: value })}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择关联的聊天" />
              </SelectTrigger>
              <SelectContent>
                {chatList.map((chat) => (
                  <SelectItem key={chat.chat_id} value={chat.chat_id}>
                    {chat.chat_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center space-x-2">
            <Switch
              id="is_global"
              checked={formData.is_global}
              onCheckedChange={(checked) => setFormData({ ...formData, is_global: checked })}
            />
            <Label htmlFor="is_global">设为全局黑话</Label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleCreate} disabled={saving}>
            {saving ? '创建中...' : '创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// 黑话编辑对话框
function JargonEditDialog({
  jargon,
  open,
  onOpenChange,
  chatList,
  onSuccess,
}: {
  jargon: Jargon | null
  open: boolean
  onOpenChange: (open: boolean) => void
  chatList: JargonChatInfo[]
  onSuccess: () => void
}) {
  const [formData, setFormData] = useState<JargonUpdateRequest>({})
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    if (jargon) {
      setFormData({
        content: jargon.content,
        meaning: jargon.meaning || '',
        chat_id: jargon.stream_id || jargon.chat_id, // 使用 stream_id 来匹配 chatList
        is_global: jargon.is_global,
        is_jargon: jargon.is_jargon,
      })
    }
  }, [jargon])

  const handleSave = async () => {
    if (!jargon) return

    try {
      setSaving(true)
      await updateJargon(jargon.id, formData)
      toast({
        title: '保存成功',
        description: '黑话已更新',
      })
      onSuccess()
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '无法更新黑话',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  if (!jargon) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>编辑黑话</DialogTitle>
          <DialogDescription>修改黑话的信息</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit_content">内容</Label>
            <Input
              id="edit_content"
              value={formData.content || ''}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              placeholder="输入黑话内容"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit_meaning">含义</Label>
            <Textarea
              id="edit_meaning"
              value={formData.meaning || ''}
              onChange={(e) => setFormData({ ...formData, meaning: e.target.value })}
              placeholder="输入黑话含义"
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit_chat_id">聊天</Label>
            <Select
              value={formData.chat_id || ''}
              onValueChange={(value) => setFormData({ ...formData, chat_id: value })}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择关联的聊天" />
              </SelectTrigger>
              <SelectContent>
                {chatList.map((chat) => (
                  <SelectItem key={chat.chat_id} value={chat.chat_id}>
                    {chat.chat_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>黑话状态</Label>
            <Select
              value={
                formData.is_jargon === null ? 'null' : formData.is_jargon?.toString() || 'null'
              }
              onValueChange={(value) =>
                setFormData({ ...formData, is_jargon: value === 'null' ? null : value === 'true' })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="null">未判定</SelectItem>
                <SelectItem value="true">是黑话</SelectItem>
                <SelectItem value="false">非黑话</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center space-x-2">
            <Switch
              id="edit_is_global"
              checked={formData.is_global}
              onCheckedChange={(checked) => setFormData({ ...formData, is_global: checked })}
            />
            <Label htmlFor="edit_is_global">全局黑话</Label>
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
