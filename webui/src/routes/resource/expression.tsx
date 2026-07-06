import {
  MessageSquare,
  Search,
  Edit,
  Trash2,
  Eye,
  Plus,
  Clock,
  Hash,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CalendarDays,
  SlidersHorizontal,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
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
import { IosListSkeleton } from '@/components/ui/skeleton'
import type {
  Expression,
  ExpressionCreateRequest,
  ExpressionUpdateRequest,
  ChatInfo,
} from '@/types/expression'
import {
  getExpressionList,
  getExpressionDetail,
  createExpression,
  updateExpression,
  deleteExpression,
  batchDeleteExpressions,
  getExpressionStats,
  getChatList,
} from '@/lib/expression-api'

export function ExpressionManagementPage() {
  const [expressions, setExpressions] = useState<Expression[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [selectedExpression, setSelectedExpression] = useState<Expression | null>(null)
  const [isDetailDialogOpen, setIsDetailDialogOpen] = useState(false)
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [deleteConfirmExpression, setDeleteConfirmExpression] = useState<Expression | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [isBatchDeleteDialogOpen, setIsBatchDeleteDialogOpen] = useState(false)
  const [jumpToPage, setJumpToPage] = useState('')
  const [stats, setStats] = useState({
    total: 0,
    recent_7days: 0,
    chat_count: 0,
    top_chats: {} as Record<string, number>,
  })
  const [chatList, setChatList] = useState<ChatInfo[]>([])
  const [chatNameMap, setChatNameMap] = useState<Map<string, string>>(new Map())
  const { toast } = useToast()

  // 加载表达方式列表
  const loadExpressions = async () => {
    try {
      setLoading(true)
      const response = await getExpressionList({
        page,
        page_size: pageSize,
        search: search || undefined,
      })
      setExpressions(response.data)
      setTotal(response.total)
    } catch (error) {
      toast({
        title: '加载失败',
        description: error instanceof Error ? error.message : '无法加载表达方式',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }

  // 加载统计数据
  const loadStats = async () => {
    try {
      const response = await getExpressionStats()
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
      const response = await getChatList()
      if (response?.data) {
        setChatList(response.data)
        // 构建聊天ID到名称的映射
        const nameMap = new Map<string, string>()
        response.data.forEach((chat) => {
          nameMap.set(chat.chat_id, chat.chat_name)
        })
        setChatNameMap(nameMap)
      }
    } catch (error) {
      console.error('加载聊天列表失败:', error)
    }
  }

  // 获取聊天名称（支持Unicode字符完整显示）
  const getChatName = (chatId: string): string => {
    return chatNameMap.get(chatId) || chatId
  }

  // 初始加载
  useEffect(() => {
    loadExpressions()
    loadStats()
    loadChatList()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search])

  // 查看详情
  const handleViewDetail = async (expression: Expression) => {
    try {
      const response = await getExpressionDetail(expression.id)
      setSelectedExpression(response.data)
      setIsDetailDialogOpen(true)
    } catch (error) {
      toast({
        title: '加载详情失败',
        description: error instanceof Error ? error.message : '无法加载表达方式详情',
        variant: 'destructive',
      })
    }
  }

  // 编辑表达方式
  const handleEdit = (expression: Expression) => {
    setSelectedExpression(expression)
    setIsEditDialogOpen(true)
  }

  // 删除表达方式
  const handleDelete = async (expression: Expression) => {
    try {
      await deleteExpression(expression.id)
      toast({
        title: '删除成功',
        description: `已删除表达方式: ${expression.situation}`,
      })
      setDeleteConfirmExpression(null)
      loadExpressions()
      loadStats()
    } catch (error) {
      toast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '无法删除表达方式',
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
    if (selectedIds.size === expressions.length && expressions.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(expressions.map((e) => e.id)))
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    try {
      await batchDeleteExpressions(Array.from(selectedIds))
      toast({
        title: '批量删除成功',
        description: `已删除 ${selectedIds.size} 个表达方式`,
      })
      setSelectedIds(new Set())
      setIsBatchDeleteDialogOpen(false)
      loadExpressions()
      loadStats()
    } catch (error) {
      toast({
        title: '批量删除失败',
        description: error instanceof Error ? error.message : '无法批量删除表达方式',
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
  const expressionStatItems = [
    {
      label: '总数量',
      value: stats.total,
      detail: '全部模板',
      Icon: MessageSquare,
      symbolClassName: 'ios-symbol-orange',
    },
    {
      label: '近7天新增',
      value: stats.recent_7days,
      detail: '最近学习',
      Icon: CalendarDays,
      symbolClassName: 'ios-symbol-green',
    },
    {
      label: '关联聊天数',
      value: stats.chat_count,
      detail: '覆盖范围',
      Icon: Hash,
      symbolClassName: 'ios-symbol-purple',
    },
  ]

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col px-5 py-5 sm:p-6">
      {/* 页面标题 */}
      <div className="mb-4 sm:mb-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">表达方式管理</h1>
            <p className="ios-subtitle">管理当前实例的表达方式和话术模板</p>
          </div>
          <Button
            onClick={() => setIsCreateDialogOpen(true)}
            className="hidden gap-2 sm:inline-flex"
          >
            <Plus className="h-4 w-4" />
            新增表达方式
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
                新增表达方式
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>

          {/* 统计 */}
          <div className="ios-stat-grid sm:grid-cols-3">
            {expressionStatItems.map(({ label, value, detail, Icon, symbolClassName }) => (
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
              placeholder="搜索情境、风格或上下文"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              className="ios-search-input"
            />
          </div>

          {/* 显示和批量操作 */}
          <div className="ios-group overflow-hidden">
            <div
              className={cn(
                'ios-row min-h-[64px]',
                selectedIds.size > 0 &&
                  'flex-col !items-stretch !justify-start gap-3 sm:flex-row sm:!items-center sm:!justify-between'
              )}
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">显示设置</span>
                  <span className="block text-[13px] leading-5 text-muted-foreground">
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

          {/* 表达方式列表 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                表达方式列表
              </p>
              {expressions.length > 0 && (
                <button
                  type="button"
                  onClick={toggleSelectAll}
                  className="ios-touch rounded-full px-2.5 py-1 text-[13px] font-medium leading-5 text-primary hover:bg-accent/60"
                >
                  {selectedIds.size === expressions.length ? '取消全选' : '全选'}
                </button>
              )}
            </div>
            <div className="ios-group overflow-hidden">
              {loading ? (
                <IosListSkeleton rows={4} />
              ) : expressions.length === 0 ? (
                <div className="ios-empty-state">
                  <span className="ios-empty-illustration">
                    <MessageSquare className="relative z-10 h-7 w-7 text-primary" />
                  </span>
                  <div>
                    <p className="text-[16px] font-semibold leading-6 text-foreground">
                      暂无表达方式
                    </p>
                    <p className="mt-1 max-w-sm text-[13px] leading-5">
                      新增模板后，这里会显示可复用的情境、风格和关联聊天。
                    </p>
                  </div>
                  <Button
                    onClick={() => setIsCreateDialogOpen(true)}
                    size="sm"
                    className="h-9 px-4"
                  >
                    <Plus className="mr-1 h-4 w-4" />
                    新增表达方式
                  </Button>
                </div>
              ) : (
                expressions.map((expression) => (
                  <div
                    key={expression.id}
                    className="ios-row min-h-[92px] flex-col !items-stretch !justify-start gap-3 py-3 sm:flex-row sm:!items-center sm:!justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <Checkbox
                        checked={selectedIds.has(expression.id)}
                        onCheckedChange={() => toggleSelect(expression.id)}
                        className="mt-2"
                      />
                      <span className="ios-symbol ios-symbol-sm ios-symbol-orange mt-0.5">
                        <MessageSquare className="h-4 w-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <h3
                          className="line-clamp-1 text-[15px] font-semibold leading-5 text-foreground"
                          title={expression.situation}
                        >
                          {expression.situation}
                        </h3>
                        <p
                          className="mt-1 line-clamp-2 text-[13px] leading-5 text-muted-foreground"
                          title={expression.style}
                        >
                          {expression.style}
                        </p>
                        <p
                          className="mt-1 truncate text-[12px] leading-4 text-muted-foreground/80"
                          title={getChatName(expression.chat_id)}
                          style={{ wordBreak: 'keep-all' }}
                        >
                          {getChatName(expression.chat_id)}
                        </p>
                      </div>
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-2 pl-14 sm:pl-0">
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => handleEdit(expression)}
                        className="h-9 rounded-full px-4"
                      >
                        <Edit className="mr-1 h-4 w-4" />
                        编辑
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        className="h-9 w-9 rounded-full"
                        onClick={() => handleViewDetail(expression)}
                        title="查看详情"
                      >
                        <Eye className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setDeleteConfirmExpression(expression)}
                        className="text-destructive hover:text-destructive h-9 rounded-full px-4"
                      >
                        <Trash2 className="mr-1 h-4 w-4" />
                        删除
                      </Button>
                    </div>
                  </div>
                ))
              )}

              {/* 分页 */}
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
      <ExpressionDetailDialog
        expression={selectedExpression}
        open={isDetailDialogOpen}
        onOpenChange={setIsDetailDialogOpen}
        chatNameMap={chatNameMap}
      />

      {/* 创建对话框 */}
      <ExpressionCreateDialog
        open={isCreateDialogOpen}
        onOpenChange={setIsCreateDialogOpen}
        chatList={chatList}
        onSuccess={() => {
          loadExpressions()
          loadStats()
          setIsCreateDialogOpen(false)
        }}
      />

      {/* 编辑对话框 */}
      <ExpressionEditDialog
        expression={selectedExpression}
        open={isEditDialogOpen}
        onOpenChange={setIsEditDialogOpen}
        chatList={chatList}
        onSuccess={() => {
          loadExpressions()
          loadStats()
          setIsEditDialogOpen(false)
        }}
      />

      {/* 删除确认对话框 */}
      <AlertDialog
        open={!!deleteConfirmExpression}
        onOpenChange={() => setDeleteConfirmExpression(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除表达方式 "{deleteConfirmExpression?.situation}" 吗？ 此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirmExpression && handleDelete(deleteConfirmExpression)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 批量删除确认对话框 */}
      <BatchDeleteConfirmDialog
        open={isBatchDeleteDialogOpen}
        onOpenChange={setIsBatchDeleteDialogOpen}
        onConfirm={handleBatchDelete}
        count={selectedIds.size}
      />
    </div>
  )
}

// 表达方式详情对话框
function ExpressionDetailDialog({
  expression,
  open,
  onOpenChange,
  chatNameMap,
}: {
  expression: Expression | null
  open: boolean
  onOpenChange: (open: boolean) => void
  chatNameMap: Map<string, string>
}) {
  if (!expression) return null

  const formatTime = (timestamp: number | null) => {
    if (!timestamp) return '-'
    return new Date(timestamp * 1000).toLocaleString('zh-CN')
  }

  const getChatName = (chatId: string): string => {
    return chatNameMap.get(chatId) || chatId
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>表达方式详情</DialogTitle>
          <DialogDescription>查看表达方式的完整信息</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <InfoItem label="情境" value={expression.situation} />
            <InfoItem label="风格" value={expression.style} />
            <InfoItem label="聊天" value={getChatName(expression.chat_id)} />
            <InfoItem icon={Hash} label="记录ID" value={expression.id.toString()} mono />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <InfoItem icon={Clock} label="创建时间" value={formatTime(expression.create_date)} />
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

// 表达方式创建对话框
function ExpressionCreateDialog({
  open,
  onOpenChange,
  chatList,
  onSuccess,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  chatList: ChatInfo[]
  onSuccess: () => void
}) {
  const [formData, setFormData] = useState<ExpressionCreateRequest>({
    situation: '',
    style: '',
    chat_id: '',
  })
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  const handleCreate = async () => {
    if (!formData.situation || !formData.style || !formData.chat_id) {
      toast({
        title: '验证失败',
        description: '请填写必填字段：情境、风格和聊天',
        variant: 'destructive',
      })
      return
    }

    try {
      setSaving(true)
      await createExpression(formData)
      toast({
        title: '创建成功',
        description: '表达方式已创建',
      })
      // 重置表单
      setFormData({
        situation: '',
        style: '',
        chat_id: '',
      })
      onSuccess()
    } catch (error) {
      toast({
        title: '创建失败',
        description: error instanceof Error ? error.message : '无法创建表达方式',
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
          <DialogTitle>新增表达方式</DialogTitle>
          <DialogDescription>创建新的表达方式记录</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="situation">
                情境 <span className="text-destructive">*</span>
              </Label>
              <Input
                id="situation"
                value={formData.situation}
                onChange={(e) => setFormData({ ...formData, situation: e.target.value })}
                placeholder="描述使用场景"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="style">
                风格 <span className="text-destructive">*</span>
              </Label>
              <Input
                id="style"
                value={formData.style}
                onChange={(e) => setFormData({ ...formData, style: e.target.value })}
                placeholder="描述表达风格"
              />
            </div>
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
                    <span className="truncate" style={{ wordBreak: 'keep-all' }}>
                      {chat.chat_name}
                      {chat.is_group && <span className="ml-1 text-muted-foreground">(群聊)</span>}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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

// 表达方式编辑对话框
function ExpressionEditDialog({
  expression,
  open,
  onOpenChange,
  chatList,
  onSuccess,
}: {
  expression: Expression | null
  open: boolean
  onOpenChange: (open: boolean) => void
  chatList: ChatInfo[]
  onSuccess: () => void
}) {
  const [formData, setFormData] = useState<ExpressionUpdateRequest>({})
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    if (expression) {
      setFormData({
        situation: expression.situation,
        style: expression.style,
        chat_id: expression.chat_id,
      })
    }
  }, [expression])

  const handleSave = async () => {
    if (!expression) return

    try {
      setSaving(true)
      await updateExpression(expression.id, formData)
      toast({
        title: '保存成功',
        description: '表达方式已更新',
      })
      onSuccess()
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '无法更新表达方式',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  if (!expression) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>编辑表达方式</DialogTitle>
          <DialogDescription>修改表达方式的信息</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="edit_situation">情境</Label>
              <Input
                id="edit_situation"
                value={formData.situation || ''}
                onChange={(e) => setFormData({ ...formData, situation: e.target.value })}
                placeholder="描述使用场景"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit_style">风格</Label>
              <Input
                id="edit_style"
                value={formData.style || ''}
                onChange={(e) => setFormData({ ...formData, style: e.target.value })}
                placeholder="描述表达风格"
              />
            </div>
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
                    <span className="truncate" style={{ wordBreak: 'keep-all' }}>
                      {chat.chat_name}
                      {chat.is_group && <span className="ml-1 text-muted-foreground">(群聊)</span>}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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

// 批量删除确认对话框
function BatchDeleteConfirmDialog({
  open,
  onOpenChange,
  onConfirm,
  count,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  count: number
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认批量删除</AlertDialogTitle>
          <AlertDialogDescription>
            您即将删除 {count} 个表达方式，此操作无法撤销。确定要继续吗？
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            确认删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
