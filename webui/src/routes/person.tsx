import {
  Users,
  Search,
  Edit,
  Trash2,
  Eye,
  User,
  MessageSquare,
  Hash,
  Clock,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  SlidersHorizontal,
  MoreHorizontal,
} from 'lucide-react'
import { useState, useEffect, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
import { Checkbox } from '@/components/ui/checkbox'
import { IosListSkeleton } from '@/components/ui/skeleton'
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
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { PersonInfo, PersonUpdateRequest } from '@/types/person'
import {
  getPersonList,
  getPersonDetail,
  updatePerson,
  deletePerson,
  getPersonStats,
  batchDeletePersons,
} from '@/lib/person-api'

function getProfileDisplayName(person: PersonInfo): string {
  return person.person_name || person.nickname || person.user_id
}

function getProfileSummary(person: PersonInfo): string {
  if (person.memory_points) return person.memory_points
  const interests = person.profile_interests?.slice(0, 3).join('、')
  if (interests) return `兴趣：${interests}`
  const preferences = Object.entries(person.profile_preferences || {})
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${value}`)
    .join('；')
  if (preferences) return `偏好：${preferences}`
  const facts = Object.entries(person.profile_facts || {})
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${value}`)
    .join('；')
  if (facts) return `事实：${facts}`
  return '画像正在收集中'
}

function objectCount(value: Record<string, unknown> | Record<string, string> | undefined): number {
  return value ? Object.keys(value).length : 0
}

const PERSON_STATUS_OPTIONS = [
  { value: 'all', label: '全部', description: '显示所有用户画像' },
  { value: 'true', label: '可用于回复', description: '只看参与回复参考的画像' },
  { value: 'false', label: '隐藏画像', description: '只看不参与回复的画像' },
] as const

const personActionClass =
  'ios-touch flex min-h-[50px] w-full items-center gap-3 border-b border-border/45 px-3.5 py-2.5 text-left text-[15px] font-medium leading-5 last:border-b-0 hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:ring-0'

const personActionIconClass = 'ios-symbol ios-symbol-sm'

export function PersonManagementPage() {
  const [persons, setPersons] = useState<PersonInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [filterKnown, setFilterKnown] = useState<boolean | undefined>(undefined)
  const [filterPlatform, setFilterPlatform] = useState<string | undefined>(undefined)
  const [selectedPerson, setSelectedPerson] = useState<PersonInfo | null>(null)
  const [isDetailDialogOpen, setIsDetailDialogOpen] = useState(false)
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [deleteConfirmPerson, setDeleteConfirmPerson] = useState<PersonInfo | null>(null)
  const [stats, setStats] = useState({
    total: 0,
    known: 0,
    unknown: 0,
    platforms: {} as Record<string, number>,
  })
  const [selectedPersons, setSelectedPersons] = useState<Set<string>>(new Set())
  const [batchDeleteDialogOpen, setBatchDeleteDialogOpen] = useState(false)
  const [jumpToPage, setJumpToPage] = useState('')
  const { toast } = useToast()

  // 加载人物列表
  const loadPersons = async () => {
    try {
      setLoading(true)
      const response = await getPersonList({
        page,
        page_size: pageSize,
        search: search || undefined,
        is_known: filterKnown,
        platform: filterPlatform,
      })
      setPersons(response.data)
      setTotal(response.total)
    } catch (error) {
      toast({
        title: '加载失败',
        description: error instanceof Error ? error.message : '无法加载人物信息',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }

  // 加载统计数据
  const loadStats = async () => {
    try {
      const response = await getPersonStats()
      if (response?.data) {
        setStats(response.data)
      }
    } catch (error) {
      console.error('加载统计数据失败:', error)
    }
  }

  // 初始加载
  useEffect(() => {
    loadPersons()
    loadStats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, filterKnown, filterPlatform])

  // 查看详情
  const handleViewDetail = async (person: PersonInfo) => {
    try {
      const response = await getPersonDetail(person.person_id)
      setSelectedPerson(response.data)
      setIsDetailDialogOpen(true)
    } catch (error) {
      toast({
        title: '加载详情失败',
        description: error instanceof Error ? error.message : '无法加载人物详情',
        variant: 'destructive',
      })
    }
  }

  // 编辑显示备注
  const handleEdit = (person: PersonInfo) => {
    setSelectedPerson(person)
    setIsEditDialogOpen(true)
  }

  // 删除人物
  const handleDelete = async (person: PersonInfo) => {
    try {
      await deletePerson(person.person_id)
      toast({
        title: '删除成功',
        description: `已删除用户画像: ${getProfileDisplayName(person)}`,
      })
      setDeleteConfirmPerson(null)
      loadPersons()
      loadStats()
    } catch (error) {
      toast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '无法删除人物信息',
        variant: 'destructive',
      })
    }
  }

  // 获取平台列表
  const platforms = useMemo(() => {
    return Object.keys(stats.platforms)
  }, [stats.platforms])
  const currentKnownValue = filterKnown === undefined ? 'all' : filterKnown.toString()
  const currentKnownLabel =
    PERSON_STATUS_OPTIONS.find((option) => option.value === currentKnownValue)?.label ?? '全部'
  const currentPlatformLabel = filterPlatform || '全部平台'

  // 切换单个人物选择
  const togglePersonSelection = (personId: string) => {
    const newSelected = new Set(selectedPersons)
    if (newSelected.has(personId)) {
      newSelected.delete(personId)
    } else {
      newSelected.add(personId)
    }
    setSelectedPersons(newSelected)
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedPersons.size === persons.length && persons.length > 0) {
      setSelectedPersons(new Set())
    } else {
      setSelectedPersons(new Set(persons.map((p) => p.person_id)))
    }
  }

  // 打开批量删除对话框
  const openBatchDeleteDialog = () => {
    if (selectedPersons.size === 0) {
      toast({
        title: '未选择任何人物',
        description: '请先选择要删除的用户画像',
        variant: 'destructive',
      })
      return
    }
    setBatchDeleteDialogOpen(true)
  }

  // 批量删除确认
  const handleBatchDelete = async () => {
    try {
      const result = await batchDeletePersons(Array.from(selectedPersons))
      toast({
        title: '批量删除完成',
        description: result.message,
      })
      setSelectedPersons(new Set())
      setBatchDeleteDialogOpen(false)
      loadPersons()
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

  // 格式化时间
  const formatTime = (timestamp: number | null) => {
    if (!timestamp) return '-'
    return new Date(timestamp * 1000).toLocaleString('zh-CN')
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] min-w-0 flex-col overflow-x-hidden px-5 py-5 sm:p-6">
      {/* 页面标题 */}
      <div className="mb-4 sm:mb-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">用户画像</h1>
            <p className="ios-subtitle">查看当前实例从新记忆系统聚合出的用户画像</p>
          </div>
        </div>
      </div>

      {/* Radix's table wrapper otherwise adopts the list rows' intrinsic width. */}
      <ScrollArea className="min-h-0 min-w-0 flex-1 [&>[data-radix-scroll-area-viewport]>div]:!block [&>[data-radix-scroll-area-viewport]>div]:!w-full [&>[data-radix-scroll-area-viewport]>div]:!min-w-0">
        <div className="w-full min-w-0 max-w-full space-y-4 sm:space-y-6 sm:pr-4">
          {/* 统计 */}
          <div className="ios-group overflow-hidden">
            <div className="ios-row">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                  <Users className="h-4 w-4" />
                </span>
                <span className="text-[16px] font-normal leading-6">画像总数</span>
              </span>
              <span className="ios-value">{stats.total}</span>
            </div>
            <div className="ios-row">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                  <Eye className="h-4 w-4" />
                </span>
                <span className="text-[16px] font-normal leading-6">可用于回复</span>
              </span>
              <span className="ios-value">{stats.known}</span>
            </div>
            <div className="ios-row">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                  <User className="h-4 w-4" />
                </span>
                <span className="text-[16px] font-normal leading-6">隐藏画像</span>
              </span>
              <span className="ios-value">{stats.unknown}</span>
            </div>
          </div>

          <div className="ios-search-field">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="search"
              placeholder="搜索用户、印象、兴趣、偏好或事实"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              className="ios-search-input"
            />
          </div>

          {/* 筛选和显示 */}
          <div className="ios-group overflow-hidden">
            <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="block truncate text-[16px] font-normal leading-6">画像状态</span>
              </span>
              <Select
                value={currentKnownValue}
                onValueChange={(value) => {
                  setFilterKnown(value === 'all' ? undefined : value === 'true')
                  setPage(1)
                }}
              >
                <SelectTrigger
                  id="filter-known"
                  className="h-auto min-h-11 w-full justify-between gap-2 rounded-[14px] border-0 bg-secondary/60 px-3 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-secondary/70 focus:ring-0 sm:w-auto sm:max-w-[9rem] sm:justify-end sm:gap-1 sm:bg-transparent sm:px-0 sm:hover:bg-transparent [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERSON_STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-teal">
                  <MessageSquare className="h-4 w-4" />
                </span>
                <span className="block truncate text-[16px] font-normal leading-6">平台</span>
              </span>
              <Select
                value={filterPlatform || 'all'}
                onValueChange={(value) => {
                  setFilterPlatform(value === 'all' ? undefined : value)
                  setPage(1)
                }}
              >
                <SelectTrigger
                  id="filter-platform"
                  className="h-auto min-h-11 w-full justify-between gap-2 rounded-[14px] border-0 bg-secondary/60 px-3 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-secondary/70 focus:ring-0 sm:w-auto sm:max-w-[11rem] sm:justify-end sm:gap-1 sm:bg-transparent sm:px-0 sm:hover:bg-transparent [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部平台</SelectItem>
                  {platforms.map((platform) => (
                    <SelectItem key={platform} value={platform}>
                      {platform} ({stats.platforms[platform]})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div
              className={cn(
                'ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-3 py-3 sm:flex-row sm:!items-center sm:!justify-between'
              )}
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">显示设置</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentKnownLabel} · {currentPlatformLabel} · 已选 {selectedPersons.size}
                  </span>
                </span>
              </span>
              <div className="flex w-full shrink-0 flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
                <Select
                  value={pageSize.toString()}
                  onValueChange={(value) => {
                    setPageSize(parseInt(value))
                    setPage(1)
                    setSelectedPersons(new Set())
                  }}
                >
                  <SelectTrigger
                    id="page-size"
                    className="h-auto min-h-11 w-full justify-between gap-2 rounded-[14px] border-0 bg-secondary/60 px-3 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-secondary/70 focus:ring-0 sm:w-auto sm:max-w-[8rem] sm:justify-end sm:gap-1 sm:bg-transparent sm:px-0 sm:hover:bg-transparent [&>svg]:h-4 [&>svg]:w-4"
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
                {selectedPersons.size > 0 && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedPersons(new Set())}
                      className="h-11 rounded-full px-4"
                    >
                      取消选择
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={openBatchDeleteDialog}
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

          {/* 人物列表 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">画像列表</p>
              {persons.length > 0 && (
                <button
                  type="button"
                  onClick={toggleSelectAll}
                  className="ios-touch min-h-11 rounded-full px-3.5 py-2 text-[13px] font-medium leading-5 text-primary hover:bg-accent/60"
                >
                  {selectedPersons.size === persons.length ? '取消全选' : '全选'}
                </button>
              )}
            </div>
            <div className="ios-group overflow-hidden">
              {loading ? (
                <IosListSkeleton rows={4} />
              ) : persons.length === 0 ? (
                <div className="ios-empty-state">
                  <span className="ios-empty-illustration">
                    <Users className="relative z-10 h-7 w-7 text-primary" />
                  </span>
                  <div>
                    <p className="text-[16px] font-semibold leading-6 text-foreground">
                      暂无用户画像
                    </p>
                    <p className="mt-1 max-w-sm text-[13px] leading-5">
                      有新的会话画像后，这里会显示用户信息、兴趣和记忆摘要。
                    </p>
                  </div>
                </div>
              ) : (
                persons.map((person) => (
                  <div
                    key={person.id}
                    className="ios-row min-h-[96px] flex-row !items-start !justify-between gap-3 py-3 sm:!items-center"
                  >
                    <div className="flex min-w-0 flex-1 items-start gap-3">
                      <Checkbox
                        checked={selectedPersons.has(person.person_id)}
                        onCheckedChange={() => togglePersonSelection(person.person_id)}
                        className="mt-2 shrink-0"
                        aria-label={`选择 ${getProfileDisplayName(person)}`}
                      />
                      <span
                        className={cn(
                          'ios-symbol ios-symbol-sm mt-0.5',
                          person.is_known ? 'ios-symbol-green' : 'ios-symbol-gray'
                        )}
                      >
                        <User className="h-4 w-4" />
                      </span>
                      <button
                        type="button"
                        onClick={() => handleViewDetail(person)}
                        className="ios-touch min-w-0 flex-1 rounded-[12px] text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <span
                            className="block truncate text-[15px] font-semibold leading-5 text-foreground"
                            title={getProfileDisplayName(person)}
                          >
                            {getProfileDisplayName(person)}
                          </span>
                          <span
                            className={cn(
                              'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4',
                              person.is_known
                                ? 'bg-[rgb(52_199_89_/_0.12)] text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
                                : 'bg-muted text-muted-foreground'
                            )}
                          >
                            {person.is_known ? '可用' : '隐藏'}
                          </span>
                        </span>
                        <span
                          className="mt-1 line-clamp-2 text-[13px] leading-5 text-muted-foreground"
                          title={getProfileSummary(person)}
                        >
                          {getProfileSummary(person)}
                        </span>
                        <span className="mt-1 block truncate text-[12px] leading-4 text-muted-foreground/80">
                          {person.platform} · {person.profile_interests?.length || 0} 兴趣 ·{' '}
                          {objectCount(person.profile_preferences)} 偏好 ·{' '}
                          {objectCount(person.profile_facts)} 事实 · {formatTime(person.last_know)}
                        </span>
                      </button>
                    </div>

                    <div className="flex shrink-0 justify-end">
                      <Popover>
                        <PopoverTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-11 w-11 rounded-[14px]"
                            title="更多操作"
                          >
                            <MoreHorizontal className="h-5 w-5" />
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent align="end" className="w-52 p-1.5">
                          <div className="overflow-hidden rounded-[14px]">
                            <button
                              type="button"
                              className={personActionClass}
                              onClick={() => handleViewDetail(person)}
                            >
                              <span className={cn(personActionIconClass, 'ios-symbol-blue')}>
                                <Eye className="h-[18px] w-[18px]" />
                              </span>
                              详情
                            </button>
                            <button
                              type="button"
                              className={personActionClass}
                              onClick={() => handleEdit(person)}
                            >
                              <span className={cn(personActionIconClass, 'ios-symbol-purple')}>
                                <Edit className="h-[18px] w-[18px]" />
                              </span>
                              备注
                            </button>
                            <button
                              type="button"
                              className={cn(personActionClass, 'text-destructive')}
                              onClick={() => setDeleteConfirmPerson(person)}
                            >
                              <span className={cn(personActionIconClass, 'ios-symbol-red')}>
                                <Trash2 className="h-[18px] w-[18px]" />
                              </span>
                              删除
                            </button>
                          </div>
                        </PopoverContent>
                      </Popover>
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
                      className="hidden h-11 w-11 rounded-full sm:inline-flex"
                    >
                      <ChevronsLeft className="h-4 w-4" />
                    </Button>

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage(page - 1)}
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
                        max={Math.ceil(total / pageSize)}
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
                      onClick={() => setPage(page + 1)}
                      disabled={page >= Math.ceil(total / pageSize)}
                      className="h-11 rounded-full px-4"
                    >
                      <span className="hidden sm:inline">下一页</span>
                      <ChevronRight className="h-4 w-4 sm:ml-1" />
                    </Button>

                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setPage(Math.ceil(total / pageSize))}
                      disabled={page >= Math.ceil(total / pageSize)}
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
      </ScrollArea>

      {/* 详情对话框 */}
      <PersonDetailDialog
        person={selectedPerson}
        open={isDetailDialogOpen}
        onOpenChange={setIsDetailDialogOpen}
      />

      {/* 编辑对话框 */}
      <PersonEditDialog
        person={selectedPerson}
        open={isEditDialogOpen}
        onOpenChange={setIsEditDialogOpen}
        onSuccess={() => {
          loadPersons()
          loadStats()
          setIsEditDialogOpen(false)
        }}
      />

      {/* 删除确认对话框 */}
      <AlertDialog open={!!deleteConfirmPerson} onOpenChange={() => setDeleteConfirmPerson(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除用户画像 "
              {deleteConfirmPerson ? getProfileDisplayName(deleteConfirmPerson) : ''}" 吗？
              此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirmPerson && handleDelete(deleteConfirmPerson)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 批量删除确认对话框 */}
      <AlertDialog open={batchDeleteDialogOpen} onOpenChange={setBatchDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认批量删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除选中的 {selectedPersons.size} 个用户画像吗？ 此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleBatchDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              批量删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// 人物详情对话框
function PersonDetailDialog({
  person,
  open,
  onOpenChange,
}: {
  person: PersonInfo | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  if (!person) return null

  const formatTime = (timestamp: number | null) => {
    if (!timestamp) return '-'
    return new Date(timestamp * 1000).toLocaleString('zh-CN')
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>用户画像详情</DialogTitle>
          <DialogDescription>查看 {getProfileDisplayName(person)} 的结构化画像</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 基本信息 */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <InfoItem icon={User} label="显示名称" value={getProfileDisplayName(person)} />
            <InfoItem icon={MessageSquare} label="昵称" value={person.nickname} />
            <InfoItem icon={Hash} label="用户ID" value={person.user_id} mono />
            <InfoItem icon={Hash} label="画像ID" value={person.person_id} mono />
            <InfoItem label="平台" value={person.platform} />
            <InfoItem label="群名片" value={person.cardname} />
            <InfoItem label="人物类型" value={person.person_type} />
            <InfoItem label="身份来源" value={person.identity_source} />
            <InfoItem label="验证状态" value={person.verification_status} />
            <InfoItem label="状态" value={person.is_known ? '可用于回复' : '隐藏画像'} />
          </div>

          {/* 印象 */}
          {person.memory_points && (
            <div className="ios-group p-4">
              <Label className="text-xs text-muted-foreground">画像印象</Label>
              <p className="mt-1 whitespace-pre-wrap text-sm">{person.memory_points}</p>
            </div>
          )}

          {person.profile_expression_style && (
            <div className="ios-group p-4">
              <Label className="text-xs text-muted-foreground">表达风格</Label>
              <p className="mt-1 whitespace-pre-wrap text-sm">{person.profile_expression_style}</p>
            </div>
          )}

          <ProfileListSection title="兴趣" items={person.profile_interests} />
          <ProfileMapSection title="偏好" data={person.profile_preferences} />
          <ProfileMapSection title="事实" data={person.profile_facts} />
          <ProfileTraitSection traits={person.profile_traits} />
          <ProfileMapSection title="行为统计" data={person.profile_stats} />
          <ProfileMapSection title="表达模式" data={person.profile_expression_patterns} />

          {/* 时间信息 */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <InfoItem icon={Clock} label="画像创建" value={formatTime(person.know_times)} />
            <InfoItem icon={Clock} label="首次记录" value={formatTime(person.know_since)} />
            <InfoItem icon={Clock} label="最后更新" value={formatTime(person.last_know)} />
            <InfoItem icon={Clock} label="最后提取" value={formatTime(person.last_extracted_at)} />
            <InfoItem label="情绪记录" value={`${person.mood_history_count || 0} 条`} />
          </div>
        </div>

        <DialogFooter>
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
  icon?: typeof User
  label: string
  value: string | number | null | undefined
  mono?: boolean
}) {
  return (
    <div className="space-y-1">
      <Label className="flex items-center gap-1 text-xs text-muted-foreground">
        {Icon && <Icon className="h-3 w-3" />}
        {label}
      </Label>
      <div
        className={cn(
          'break-words text-sm',
          mono && 'font-mono',
          !value && 'text-muted-foreground'
        )}
      >
        {value || '-'}
      </div>
    </div>
  )
}

function ProfileListSection({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null

  return (
    <div className="ios-group p-4">
      <Label className="text-xs text-muted-foreground">{title}</Label>
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((item) => (
          <span key={item} className="rounded-full bg-muted/70 px-2.5 py-1 text-xs">
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function ProfileMapSection({ title, data }: { title: string; data?: Record<string, unknown> }) {
  const entries = Object.entries(data || {})
  if (entries.length === 0) return null

  return (
    <div className="ios-group p-4">
      <Label className="text-xs text-muted-foreground">{title}</Label>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {entries.map(([key, value]) => (
          <div key={key} className="min-w-0 rounded-[12px] bg-muted/55 p-3">
            <div className="break-all text-xs text-muted-foreground">{key}</div>
            <div className="mt-1 break-words text-sm">{formatProfileValue(value)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ProfileTraitSection({ traits }: { traits?: Record<string, number> }) {
  const entries = Object.entries(traits || {})
  if (entries.length === 0) return null

  return (
    <div className="ios-group p-4">
      <Label className="text-xs text-muted-foreground">特征</Label>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {entries.map(([name, confidence]) => (
          <div key={name} className="rounded-[12px] bg-muted/55 p-3">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="break-words">{name}</span>
              <span className="text-xs text-muted-foreground">{Math.round(confidence * 100)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function formatProfileValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

// 人物编辑对话框
function PersonEditDialog({
  person,
  open,
  onOpenChange,
  onSuccess,
}: {
  person: PersonInfo | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: () => void
}) {
  const [formData, setFormData] = useState<PersonUpdateRequest>({})
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    if (person) {
      setFormData({
        person_name: person.person_name || '',
        name_reason: person.name_reason || '',
        nickname: person.nickname || '',
        memory_points: person.memory_points || '',
        is_known: person.is_known,
      })
    }
  }, [person])

  const handleSave = async () => {
    if (!person) return

    try {
      setSaving(true)
      await updatePerson(person.person_id, formData)
      toast({
        title: '保存成功',
        description: '显示备注已更新',
      })
      onSuccess()
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '无法更新人物信息',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  if (!person) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>编辑显示备注</DialogTitle>
          <DialogDescription>
            为 {getProfileDisplayName(person)} 设置 WebUI
            显示信息，不修改自动提取的画像事实、偏好和兴趣
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="person_name">显示名称</Label>
              <Input
                id="person_name"
                value={formData.person_name || ''}
                onChange={(e) => setFormData({ ...formData, person_name: e.target.value })}
                placeholder="仅用于 WebUI 显示"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="nickname">显示昵称</Label>
              <Input
                id="nickname"
                value={formData.nickname || ''}
                onChange={(e) => setFormData({ ...formData, nickname: e.target.value })}
                placeholder="仅用于 WebUI 显示"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="name_reason">备注来源</Label>
            <Textarea
              id="name_reason"
              value={formData.name_reason || ''}
              onChange={(e) => setFormData({ ...formData, name_reason: e.target.value })}
              placeholder="说明这个显示名称或备注的来源"
              rows={2}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="memory_points">显示摘要覆盖</Label>
            <Textarea
              id="memory_points"
              value={formData.memory_points || ''}
              onChange={(e) => setFormData({ ...formData, memory_points: e.target.value })}
              placeholder="留空时使用记忆系统自动生成的画像印象"
              rows={4}
            />
          </div>

          <div className="ios-group flex min-h-[72px] items-center justify-between gap-4 p-4">
            <div>
              <Label htmlFor="is_known" className="text-base font-medium">
                可用于回复
              </Label>
              <p className="text-sm text-muted-foreground">关闭后此画像会在 WebUI 中标记为隐藏</p>
            </div>
            <Switch
              id="is_known"
              checked={formData.is_known}
              onCheckedChange={(checked) => setFormData({ ...formData, is_known: checked })}
            />
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
