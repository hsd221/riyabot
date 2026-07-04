import { Users, Search, Edit, Trash2, Eye, User, MessageSquare, Hash, Clock, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { useState, useEffect, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
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
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { PersonInfo, PersonUpdateRequest } from '@/types/person'
import { getPersonList, getPersonDetail, updatePerson, deletePerson, getPersonStats, batchDeletePersons } from '@/lib/person-api'

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
  const [stats, setStats] = useState({ total: 0, known: 0, unknown: 0, platforms: {} as Record<string, number> })
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
      setSelectedPersons(new Set(persons.map(p => p.person_id)))
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
    <div className="h-[calc(100vh-4rem)] flex flex-col p-4 sm:p-6">
      {/* 页面标题 */}
      <div className="mb-4 sm:mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold flex items-center gap-2">
              <Users className="h-8 w-8" strokeWidth={2} />
              用户画像
            </h1>
            <p className="text-muted-foreground mt-1 text-sm sm:text-base">
              查看璃夜从新记忆系统聚合出的用户画像
            </p>
          </div>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-4 sm:space-y-6 pr-4">

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="rounded-lg border bg-card p-4">
          <div className="text-sm text-muted-foreground">画像总数</div>
          <div className="text-2xl font-bold mt-1">{stats.total}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-sm text-muted-foreground">可用于回复</div>
          <div className="text-2xl font-bold mt-1 text-green-600">{stats.known}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-sm text-muted-foreground">隐藏画像</div>
          <div className="text-2xl font-bold mt-1 text-muted-foreground">{stats.unknown}</div>
        </div>
      </div>

      {/* 搜索和过滤 */}
      <div className="rounded-lg border bg-card p-4">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div className="sm:col-span-2">
            <Label htmlFor="search">搜索</Label>
            <div className="relative mt-1.5">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="search"
                placeholder="搜索用户、印象、兴趣、偏好或事实..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="filter-known">画像状态</Label>
            <Select
              value={filterKnown === undefined ? 'all' : filterKnown.toString()}
              onValueChange={(value) => {
                setFilterKnown(value === 'all' ? undefined : value === 'true')
                setPage(1)
              }}
            >
              <SelectTrigger id="filter-known" className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部</SelectItem>
                <SelectItem value="true">可用于回复</SelectItem>
                <SelectItem value="false">隐藏画像</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="filter-platform">平台</Label>
            <Select
              value={filterPlatform || 'all'}
              onValueChange={(value) => {
                setFilterPlatform(value === 'all' ? undefined : value)
                setPage(1)
              }}
            >
              <SelectTrigger id="filter-platform" className="mt-1.5">
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
        </div>

        {/* 批量操作工具栏 */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mt-4 pt-4 border-t">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            {selectedPersons.size > 0 && (
              <span>已选择 {selectedPersons.size} 个画像</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="page-size" className="text-sm whitespace-nowrap">每页显示</Label>
            <Select
              value={pageSize.toString()}
              onValueChange={(value) => {
                setPageSize(parseInt(value))
                setPage(1)
                setSelectedPersons(new Set())
              }}
            >
              <SelectTrigger id="page-size" className="w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="10">10</SelectItem>
                <SelectItem value="20">20</SelectItem>
                <SelectItem value="50">50</SelectItem>
                <SelectItem value="100">100</SelectItem>
              </SelectContent>
            </Select>
            {selectedPersons.size > 0 && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedPersons(new Set())}
                >
                  取消选择
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={openBatchDeleteDialog}
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  批量删除画像
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* 人物列表 */}
      <div className="rounded-lg border bg-card">
        {/* 桌面端表格视图 */}
        <div className="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
                  <Checkbox
                    checked={persons.length > 0 && selectedPersons.size === persons.length}
                    onCheckedChange={toggleSelectAll}
                    aria-label="全选"
                  />
                </TableHead>
                <TableHead>状态</TableHead>
                <TableHead>用户</TableHead>
                <TableHead>画像摘要</TableHead>
                <TableHead>平台</TableHead>
                <TableHead>兴趣/偏好</TableHead>
                <TableHead>事实/情绪</TableHead>
                <TableHead>最后更新</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                    加载中...
                  </TableCell>
                </TableRow>
              ) : persons.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                    暂无数据
                  </TableCell>
                </TableRow>
              ) : (
                persons.map((person) => (
                  <TableRow key={person.id}>
                    <TableCell>
                      <Checkbox
                        checked={selectedPersons.has(person.person_id)}
                        onCheckedChange={() => togglePersonSelection(person.person_id)}
                        aria-label={`选择 ${getProfileDisplayName(person)}`}
                      />
                    </TableCell>
                    <TableCell>
                      <div className={cn(
                        'inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium',
                        person.is_known
                          ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                          : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400'
                      )}>
                        {person.is_known ? '可用' : '隐藏'}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <div className="font-medium max-w-[12rem] truncate" title={getProfileDisplayName(person)}>
                          {getProfileDisplayName(person)}
                        </div>
                        <div className="font-mono text-xs text-muted-foreground max-w-[12rem] truncate" title={person.user_id}>
                          {person.user_id}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="max-w-[22rem]">
                      <div className="text-sm line-clamp-2" title={getProfileSummary(person)}>
                        {getProfileSummary(person)}
                      </div>
                    </TableCell>
                    <TableCell>{person.platform}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {person.profile_interests?.length || 0} 兴趣 / {objectCount(person.profile_preferences)} 偏好
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {objectCount(person.profile_facts)} 事实 / {person.mood_history_count || 0} 情绪
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatTime(person.last_know)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="default"
                          size="sm"
                          onClick={() => handleViewDetail(person)}
                        >
                          <Eye className="h-4 w-4 mr-1" />
                          详情
                        </Button>
                        <Button
                          variant="default"
                          size="sm"
                          onClick={() => handleEdit(person)}
                        >
                          <Edit className="h-4 w-4 mr-1" />
                          备注
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => setDeleteConfirmPerson(person)}
                          className="bg-red-600 hover:bg-red-700 text-white"
                        >
                          <Trash2 className="h-4 w-4 mr-1" />
                          删除
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {/* 移动端卡片视图 */}
        <div className="md:hidden space-y-3 p-4">
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">
              加载中...
            </div>
          ) : persons.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              暂无数据
            </div>
          ) : (
            persons.map((person) => (
              <div key={person.id} className="rounded-lg border bg-card p-4 space-y-3 overflow-hidden">
                {/* 复选框和状态 */}
                <div className="flex items-start gap-3">
                  <Checkbox
                    checked={selectedPersons.has(person.person_id)}
                    onCheckedChange={() => togglePersonSelection(person.person_id)}
                    className="mt-1"
                  />
                  <div className="flex-1 min-w-0">
                    <div className={cn(
                      'inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium mb-2',
                      person.is_known
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400'
                    )}>
                      {person.is_known ? '可用于回复' : '隐藏画像'}
                    </div>
                    <h3 className="font-semibold text-sm line-clamp-1 w-full break-all">
                      {getProfileDisplayName(person)}
                    </h3>
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-2 w-full break-all">
                      {getProfileSummary(person)}
                    </p>
                  </div>
                </div>

                {/* 平台和用户信息 */}
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">平台</div>
                    <p className="font-medium text-xs">{person.platform}</p>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">用户ID</div>
                    <p className="font-mono text-xs truncate" title={person.user_id}>{person.user_id}</p>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">兴趣/偏好</div>
                    <p className="text-xs">{person.profile_interests?.length || 0} / {objectCount(person.profile_preferences)}</p>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">事实/情绪</div>
                    <p className="text-xs">{objectCount(person.profile_facts)} / {person.mood_history_count || 0}</p>
                  </div>
                  <div className="col-span-2">
                    <div className="text-xs text-muted-foreground mb-1">最后更新</div>
                    <p className="text-xs">{formatTime(person.last_know)}</p>
                  </div>
                </div>

                {/* 操作按钮 */}
                <div className="flex flex-wrap gap-1 pt-2 border-t overflow-hidden">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleViewDetail(person)}
                    className="text-xs px-2 py-1 h-auto flex-shrink-0"
                  >
                    <Eye className="h-3 w-3 mr-1" />
                    查看
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleEdit(person)}
                    className="text-xs px-2 py-1 h-auto flex-shrink-0"
                  >
                    <Edit className="h-3 w-3 mr-1" />
                    备注
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setDeleteConfirmPerson(person)}
                    className="text-xs px-2 py-1 h-auto flex-shrink-0 text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3 mr-1" />
                    删除
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* 分页 - 增强版 */}
        {total > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 px-4 py-3 border-t">
            <div className="text-sm text-muted-foreground">
              共 {total} 条记录，第 {page} / {Math.ceil(total / pageSize)} 页
            </div>
            <div className="flex items-center gap-2">
              {/* 首页 */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(1)}
                disabled={page === 1}
                className="hidden sm:flex"
              >
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              
              {/* 上一页 */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(page - 1)}
                disabled={page === 1}
              >
                <ChevronLeft className="h-4 w-4 sm:mr-1" />
                <span className="hidden sm:inline">上一页</span>
              </Button>

              {/* 页码跳转 */}
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  value={jumpToPage}
                  onChange={(e) => setJumpToPage(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleJumpToPage()}
                  placeholder={page.toString()}
                  className="w-16 h-8 text-center"
                  min={1}
                  max={Math.ceil(total / pageSize)}
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleJumpToPage}
                  disabled={!jumpToPage}
                  className="h-8"
                >
                  跳转
                </Button>
              </div>
              
              {/* 下一页 */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(page + 1)}
                disabled={page >= Math.ceil(total / pageSize)}
              >
                <span className="hidden sm:inline">下一页</span>
                <ChevronRight className="h-4 w-4 sm:ml-1" />
              </Button>

              {/* 末页 */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(Math.ceil(total / pageSize))}
                disabled={page >= Math.ceil(total / pageSize)}
                className="hidden sm:flex"
              >
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
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
      <AlertDialog
        open={!!deleteConfirmPerson}
        onOpenChange={() => setDeleteConfirmPerson(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除用户画像 "{deleteConfirmPerson ? getProfileDisplayName(deleteConfirmPerson) : ''}" 吗？
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
              确定要删除选中的 {selectedPersons.size} 个用户画像吗？
              此操作不可撤销。
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
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>用户画像详情</DialogTitle>
          <DialogDescription>
            查看 {getProfileDisplayName(person)} 的结构化画像
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 基本信息 */}
          <div className="grid grid-cols-2 gap-4">
            <InfoItem icon={User} label="显示名称" value={getProfileDisplayName(person)} />
            <InfoItem icon={MessageSquare} label="昵称" value={person.nickname} />
            <InfoItem icon={Hash} label="用户ID" value={person.user_id} mono />
            <InfoItem icon={Hash} label="画像ID" value={person.person_id} mono />
            <InfoItem label="平台" value={person.platform} />
            <InfoItem label="状态" value={person.is_known ? '可用于回复' : '隐藏画像'} />
          </div>

          {/* 印象 */}
          {person.memory_points && (
            <div className="rounded-lg border bg-muted/50 p-3">
              <Label className="text-xs text-muted-foreground">画像印象</Label>
              <p className="mt-1 text-sm whitespace-pre-wrap">{person.memory_points}</p>
            </div>
          )}

          {person.profile_expression_style && (
            <div className="rounded-lg border bg-muted/50 p-3">
              <Label className="text-xs text-muted-foreground">表达风格</Label>
              <p className="mt-1 text-sm whitespace-pre-wrap">{person.profile_expression_style}</p>
            </div>
          )}

          <ProfileListSection title="兴趣" items={person.profile_interests} />
          <ProfileMapSection title="偏好" data={person.profile_preferences} />
          <ProfileMapSection title="事实" data={person.profile_facts} />
          <ProfileTraitSection traits={person.profile_traits} />
          <ProfileMapSection title="行为统计" data={person.profile_stats} />
          <ProfileMapSection title="表达模式" data={person.profile_expression_patterns} />

          {/* 时间信息 */}
          <div className="grid grid-cols-3 gap-4">
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
      <Label className="text-xs text-muted-foreground flex items-center gap-1">
        {Icon && <Icon className="h-3 w-3" />}
        {label}
      </Label>
      <div className={cn('text-sm break-words', mono && 'font-mono', !value && 'text-muted-foreground')}>
        {value || '-'}
      </div>
    </div>
  )
}

function ProfileListSection({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null

  return (
    <div className="rounded-lg border bg-muted/50 p-3">
      <Label className="text-xs text-muted-foreground">{title}</Label>
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((item) => (
          <span key={item} className="rounded-md bg-background px-2 py-1 text-xs border">
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
    <div className="rounded-lg border bg-muted/50 p-3">
      <Label className="text-xs text-muted-foreground">{title}</Label>
      <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
        {entries.map(([key, value]) => (
          <div key={key} className="rounded-md bg-background border p-2 min-w-0">
            <div className="text-xs text-muted-foreground break-all">{key}</div>
            <div className="mt-1 text-sm break-words">{formatProfileValue(value)}</div>
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
    <div className="rounded-lg border bg-muted/50 p-3">
      <Label className="text-xs text-muted-foreground">特征</Label>
      <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
        {entries.map(([name, confidence]) => (
          <div key={name} className="rounded-md bg-background border p-2">
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
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>编辑显示备注</DialogTitle>
          <DialogDescription>
            为 {getProfileDisplayName(person)} 设置 WebUI 显示信息，不修改自动提取的画像事实、偏好和兴趣
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
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

          <div className="flex items-center justify-between rounded-lg border p-3">
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
