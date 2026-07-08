import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  Ban,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Edit,
  Eye,
  Hash,
  MessageSquare,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { IosListSkeleton } from '@/components/ui/skeleton'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import {
  batchDeleteBehaviors,
  createBehavior,
  deleteBehavior,
  getBehaviorChatList,
  getBehaviorDetail,
  getBehaviorList,
  getBehaviorStats,
  updateBehavior,
} from '@/lib/behavior-api'
import type {
  BehaviorActorType,
  BehaviorChatInfo,
  BehaviorCreateRequest,
  BehaviorLearningType,
  BehaviorPattern,
  BehaviorStats,
  BehaviorUpdateRequest,
} from '@/types/behavior'

const ACTOR_OPTIONS: Array<{ value: BehaviorActorType; label: string; icon: LucideIcon }> = [
  { value: 'other_user', label: '他人行为', icon: Users },
  { value: 'group_collective', label: '群体习惯', icon: MessageSquare },
  { value: 'maibot_self', label: '自身反思', icon: Bot },
]

const LEARNING_OPTIONS: Array<{ value: BehaviorLearningType; label: string }> = [
  { value: 'observed_behavior', label: '观察学习' },
  { value: 'self_reflection', label: '自我反思' },
]

type EnabledFilter = 'all' | 'enabled' | 'disabled'
type ActorFilter = 'all' | BehaviorActorType
type LearningFilter = 'all' | BehaviorLearningType

const behaviorSelectTriggerClass =
  'h-auto min-h-11 w-full justify-between gap-2 rounded-[14px] border-0 bg-secondary/60 px-3 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-secondary/70 focus:ring-0 sm:w-auto sm:justify-end sm:gap-1 sm:bg-transparent sm:px-0 sm:hover:bg-transparent [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4'

const behaviorActionClass =
  'ios-touch flex min-h-[50px] w-full items-center gap-3 border-b border-border/45 px-3.5 py-2.5 text-left text-[15px] font-medium leading-5 last:border-b-0 hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:ring-0'

const behaviorActionIconClass = 'ios-symbol ios-symbol-sm'

interface BehaviorFormState {
  chat_id: string
  actor_type: BehaviorActorType
  learning_type: BehaviorLearningType
  action: string
  outcome: string
  source_text: string
  source_ids: string
  count: number
  score: number
  enabled: boolean
}

const emptyStats: BehaviorStats = {
  total: 0,
  enabled: 0,
  disabled: 0,
  recent_7days: 0,
  chat_count: 0,
  top_chats: {},
  actor_type_counts: {
    other_user: 0,
    group_collective: 0,
    maibot_self: 0,
  },
  learning_type_counts: {
    observed_behavior: 0,
    self_reflection: 0,
  },
}

function createEmptyForm(chatId = ''): BehaviorFormState {
  return {
    chat_id: chatId,
    actor_type: 'other_user',
    learning_type: 'observed_behavior',
    action: '',
    outcome: '',
    source_text: '',
    source_ids: '',
    count: 1,
    score: 1,
    enabled: true,
  }
}

function actorLabel(value: string) {
  return ACTOR_OPTIONS.find((option) => option.value === value)?.label ?? value
}

function learningLabel(value: string) {
  return LEARNING_OPTIONS.find((option) => option.value === value)?.label ?? value
}

function formatTime(value?: number | null) {
  if (!value) return '暂无'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

function sourceIdsFromText(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function formFromBehavior(behavior: BehaviorPattern): BehaviorFormState {
  return {
    chat_id: behavior.chat_id,
    actor_type: behavior.actor_type,
    learning_type: behavior.learning_type,
    action: behavior.action,
    outcome: behavior.outcome,
    source_text: behavior.source_text ?? '',
    source_ids: behavior.source_ids.join('\n'),
    count: behavior.count,
    score: behavior.score,
    enabled: behavior.enabled,
  }
}

function formToRequest(form: BehaviorFormState): BehaviorCreateRequest {
  return {
    chat_id: form.chat_id.trim(),
    actor_type: form.actor_type,
    learning_type: form.learning_type,
    action: form.action.trim(),
    outcome: form.outcome.trim(),
    source_text: form.source_text.trim(),
    source_ids: sourceIdsFromText(form.source_ids),
    count: Math.max(1, Math.round(form.count || 1)),
    score: Math.min(5, Math.max(0, Number(form.score) || 0)),
    enabled: form.enabled,
  }
}

export function BehaviorManagementPage() {
  const [behaviors, setBehaviors] = useState<BehaviorPattern[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [chatFilter, setChatFilter] = useState('all')
  const [enabledFilter, setEnabledFilter] = useState<EnabledFilter>('all')
  const [actorFilter, setActorFilter] = useState<ActorFilter>('all')
  const [learningFilter, setLearningFilter] = useState<LearningFilter>('all')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [chatList, setChatList] = useState<BehaviorChatInfo[]>([])
  const [stats, setStats] = useState<BehaviorStats>(emptyStats)
  const [detailBehavior, setDetailBehavior] = useState<BehaviorPattern | null>(null)
  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null)
  const [editingBehavior, setEditingBehavior] = useState<BehaviorPattern | null>(null)
  const [form, setForm] = useState<BehaviorFormState>(createEmptyForm())
  const [filterDialogOpen, setFilterDialogOpen] = useState(false)
  const [deleteConfirmBehavior, setDeleteConfirmBehavior] = useState<BehaviorPattern | null>(null)
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [jumpToPage, setJumpToPage] = useState('')
  const { toast } = useToast()

  const chatNameMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const chat of chatList) {
      map.set(chat.chat_id, chat.chat_name)
    }
    return map
  }, [chatList])

  const formChatOptions = useMemo(() => {
    if (!form.chat_id || chatList.some((chat) => chat.chat_id === form.chat_id)) {
      return chatList
    }
    return [
      {
        chat_id: form.chat_id,
        chat_name: form.chat_id,
        platform: null,
        is_group: false,
      },
      ...chatList,
    ]
  }, [chatList, form.chat_id])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const selectedCount = selectedIds.size

  const loadBehaviors = useCallback(async () => {
    try {
      setLoading(true)
      const response = await getBehaviorList({
        page,
        page_size: pageSize,
        search: search || undefined,
        chat_id: chatFilter === 'all' ? undefined : chatFilter,
        enabled:
          enabledFilter === 'all' ? undefined : enabledFilter === 'enabled',
        actor_type: actorFilter === 'all' ? undefined : actorFilter,
        learning_type: learningFilter === 'all' ? undefined : learningFilter,
      })
      setBehaviors(response.data)
      setTotal(response.total)
      setSelectedIds(new Set())
    } catch (error) {
      toast({
        title: '加载失败',
        description: error instanceof Error ? error.message : '无法加载行为模式',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [actorFilter, chatFilter, enabledFilter, learningFilter, page, pageSize, search, toast])

  const loadStats = useCallback(async () => {
    try {
      const response = await getBehaviorStats()
      if (response?.data) {
        setStats({
          ...emptyStats,
          ...response.data,
          actor_type_counts: {
            ...emptyStats.actor_type_counts,
            ...response.data.actor_type_counts,
          },
          learning_type_counts: {
            ...emptyStats.learning_type_counts,
            ...response.data.learning_type_counts,
          },
        })
      }
    } catch (error) {
      console.error('加载行为模式统计失败:', error)
    }
  }, [])

  const loadChats = useCallback(async () => {
    try {
      const response = await getBehaviorChatList()
      setChatList(response.data)
    } catch (error) {
      console.error('加载聊天列表失败:', error)
    }
  }, [])

  useEffect(() => {
    loadBehaviors()
  }, [loadBehaviors])

  useEffect(() => {
    loadStats()
    loadChats()
  }, [loadStats, loadChats])

  const refreshAll = async () => {
    await Promise.all([loadBehaviors(), loadStats()])
  }

  const openCreateDialog = () => {
    const defaultChat = chatFilter !== 'all' ? chatFilter : (chatList[0]?.chat_id ?? '')
    setForm(createEmptyForm(defaultChat))
    setEditingBehavior(null)
    setFormMode('create')
  }

  const openEditDialog = async (behavior: BehaviorPattern) => {
    try {
      const response = await getBehaviorDetail(behavior.id)
      setEditingBehavior(response.data)
      setForm(formFromBehavior(response.data))
      setFormMode('edit')
    } catch (error) {
      toast({
        title: '加载失败',
        description: error instanceof Error ? error.message : '无法加载行为模式详情',
        variant: 'destructive',
      })
    }
  }

  const openDetailDialog = async (behavior: BehaviorPattern) => {
    try {
      const response = await getBehaviorDetail(behavior.id)
      setDetailBehavior(response.data)
    } catch (error) {
      toast({
        title: '加载失败',
        description: error instanceof Error ? error.message : '无法加载行为模式详情',
        variant: 'destructive',
      })
    }
  }

  const handleSubmitForm = async () => {
    const request = formToRequest(form)
    if (!request.chat_id || !request.action || !request.outcome) {
      toast({
        title: '保存失败',
        description: '聊天 ID、行为和结果不能为空',
        variant: 'destructive',
      })
      return
    }

    try {
      setSaving(true)
      if (formMode === 'create') {
        await createBehavior(request)
        toast({ title: '创建成功', description: '行为模式已添加' })
      } else if (formMode === 'edit' && editingBehavior) {
        await updateBehavior(editingBehavior.id, request as BehaviorUpdateRequest)
        toast({ title: '更新成功', description: '行为模式已保存' })
      }
      setFormMode(null)
      setEditingBehavior(null)
      await refreshAll()
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '无法保存行为模式',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  const handleToggleEnabled = async (behavior: BehaviorPattern, enabled: boolean) => {
    try {
      await updateBehavior(behavior.id, { enabled })
      setBehaviors((items) =>
        items.map((item) => (item.id === behavior.id ? { ...item, enabled } : item))
      )
      await loadStats()
    } catch (error) {
      toast({
        title: '更新失败',
        description: error instanceof Error ? error.message : '无法更新启用状态',
        variant: 'destructive',
      })
    }
  }

  const handleDelete = async () => {
    if (!deleteConfirmBehavior) return
    try {
      await deleteBehavior(deleteConfirmBehavior.id)
      toast({ title: '删除成功', description: '行为模式已删除' })
      setDeleteConfirmBehavior(null)
      await refreshAll()
    } catch (error) {
      toast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '无法删除行为模式',
        variant: 'destructive',
      })
    }
  }

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    try {
      await batchDeleteBehaviors(ids)
      toast({ title: '删除成功', description: `已删除 ${ids.length} 个行为模式` })
      setBatchDeleteOpen(false)
      setSelectedIds(new Set())
      await refreshAll()
    } catch (error) {
      toast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '无法批量删除行为模式',
        variant: 'destructive',
      })
    }
  }

  const toggleSelection = (id: number, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(id)
      } else {
        next.delete(id)
      }
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === behaviors.length && behaviors.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(behaviors.map((behavior) => behavior.id)))
    }
  }

  const handleSearchChange = (value: string) => {
    setSearch(value)
    setPage(1)
  }

  const handleJumpToPage = () => {
    const targetPage = parseInt(jumpToPage)
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

  const getChatName = (chatId: string) => chatNameMap.get(chatId) ?? chatId

  const behaviorStatItems = [
    {
      label: '总数量',
      value: stats.total,
      detail: '全部模式',
      Icon: BrainCircuit,
      symbolClassName: 'ios-symbol-purple',
    },
    {
      label: '已启用',
      value: stats.enabled,
      detail: '可被引用',
      Icon: CheckCircle2,
      symbolClassName: 'ios-symbol-green',
    },
    {
      label: '已停用',
      value: stats.disabled,
      detail: '不会引用',
      Icon: Ban,
      symbolClassName: 'ios-symbol-gray',
    },
    {
      label: '近7天新增',
      value: stats.recent_7days,
      detail: '最近学习',
      Icon: Activity,
      symbolClassName: 'ios-symbol-orange',
    },
  ]

  const currentChatFilterLabel =
    chatFilter === 'all' ? '全部聊天' : (chatNameMap.get(chatFilter) ?? chatFilter)
  const currentEnabledFilterLabel =
    enabledFilter === 'all' ? '全部状态' : enabledFilter === 'enabled' ? '启用' : '停用'
  const currentActorFilterLabel = actorFilter === 'all' ? '全部主体' : actorLabel(actorFilter)
  const currentLearningFilterLabel =
    learningFilter === 'all' ? '全部来源' : learningLabel(learningFilter)
  const activeFilterCount = [
    chatFilter !== 'all',
    enabledFilter !== 'all',
    actorFilter !== 'all',
    learningFilter !== 'all',
  ].filter(Boolean).length
  const mobileFilterSummary =
    activeFilterCount > 0 ? `${activeFilterCount} 个筛选已启用` : `全部行为 · 每页 ${pageSize} 条`

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col px-5 py-5 sm:p-6">
      <div className="mb-4 sm:mb-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">行为学习管理</h1>
            <p className="ios-subtitle">管理当前实例从聊天中学习到的行为模式</p>
          </div>
          <div className="hidden gap-2 sm:flex">
            <Button variant="outline" onClick={refreshAll} disabled={loading} className="gap-2">
              <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
              刷新
            </Button>
            <Button onClick={openCreateDialog} className="gap-2">
              <Plus className="h-4 w-4" />
              新增行为
            </Button>
          </div>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="w-[calc(100vw-2.5rem)] max-w-full space-y-4 overflow-x-hidden sm:w-auto sm:space-y-6 sm:pr-4">
          <button
            type="button"
            onClick={openCreateDialog}
            className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                <Plus className="h-4 w-4" />
              </span>
              <span className="block min-w-0 truncate text-[16px] font-normal leading-6">
                新增行为模式
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>

          <div className="ios-group max-w-full overflow-hidden sm:hidden">
            <div className="grid max-w-full grid-cols-2 gap-2 p-2">
              {behaviorStatItems.map(({ label, value, symbolClassName, Icon }) => (
                <div
                  key={label}
                  className="flex min-w-0 items-center gap-2 rounded-[15px] bg-muted/45 px-3 py-2.5"
                >
                  <span className={`ios-symbol ${symbolClassName} h-7 w-7 rounded-[8px]`}>
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[12px] font-medium leading-4 text-muted-foreground">
                      {label}
                    </span>
                    <span className="block truncate text-[18px] font-semibold leading-6 tabular-nums text-foreground">
                      {value}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="hidden sm:block">
            <div className="ios-stat-grid">
              {behaviorStatItems.map(({ label, value, detail, Icon, symbolClassName }) => (
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
          </div>

          <div className="ios-search-field">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => handleSearchChange(event.target.value)}
              placeholder="搜索行为、结果或来源片段"
              className="ios-search-input"
            />
          </div>

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
                    {mobileFilterSummary}
                  </span>
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </button>
            <DialogContent className="max-h-[86vh] overflow-hidden p-0 sm:max-w-md">
              <DialogHeader className="px-5 pt-5">
                <DialogTitle>筛选与显示</DialogTitle>
                <DialogDescription>调整聊天范围、状态筛选和每页数量</DialogDescription>
              </DialogHeader>
              <ScrollArea className="max-h-[calc(82vh-9rem)] px-5">
                <div className="ios-group mb-5 overflow-hidden">
                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                        <MessageSquare className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[16px] font-normal leading-6">聊天筛选</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          {currentChatFilterLabel}
                        </span>
                      </span>
                    </span>
                    <Select
                      value={chatFilter}
                      onValueChange={(value) => {
                        setChatFilter(value)
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[12rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
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
                      <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                        <CheckCircle2 className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[16px] font-normal leading-6">启用状态</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          {currentEnabledFilterLabel}
                        </span>
                      </span>
                    </span>
                    <Select
                      value={enabledFilter}
                      onValueChange={(value) => {
                        setEnabledFilter(value as EnabledFilter)
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部状态</SelectItem>
                        <SelectItem value="enabled">启用</SelectItem>
                        <SelectItem value="disabled">停用</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                        <Users className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[16px] font-normal leading-6">行为主体</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          {currentActorFilterLabel}
                        </span>
                      </span>
                    </span>
                    <Select
                      value={actorFilter}
                      onValueChange={(value) => {
                        setActorFilter(value as ActorFilter)
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部主体</SelectItem>
                        {ACTOR_OPTIONS.map((option) => (
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
                        <BrainCircuit className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[16px] font-normal leading-6">学习来源</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          {currentLearningFilterLabel}
                        </span>
                      </span>
                    </span>
                    <Select
                      value={learningFilter}
                      onValueChange={(value) => {
                        setLearningFilter(value as LearningFilter)
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[8rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部来源</SelectItem>
                        {LEARNING_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="ios-group overflow-hidden">
                  <div className="ios-row min-h-[64px]">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                        <Hash className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[16px] font-normal leading-6">每页数量</span>
                        <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                          已选 {selectedCount}
                        </span>
                      </span>
                    </span>
                    <Select
                      value={String(pageSize)}
                      onValueChange={(value) => {
                        setPageSize(Number(value))
                        setPage(1)
                        setSelectedIds(new Set())
                      }}
                    >
                      <SelectTrigger className="h-auto min-h-11 w-auto max-w-[7rem] justify-end gap-1 border-0 bg-transparent px-0 py-0 text-[16px] font-normal leading-5 text-muted-foreground shadow-none hover:bg-transparent focus:ring-0 [&>span]:truncate [&>svg]:h-4 [&>svg]:w-4">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {[10, 20, 50, 100].map((size) => (
                          <SelectItem key={size} value={String(size)}>
                            {size} 条
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </ScrollArea>
              <DialogFooter className="px-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
                <Button onClick={() => setFilterDialogOpen(false)} className="w-full">
                  完成
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <div className="ios-group hidden overflow-hidden sm:block">
            <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                  <MessageSquare className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">聊天筛选</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentChatFilterLabel}
                  </span>
                </span>
              </span>
              <Select
                value={chatFilter}
                onValueChange={(value) => {
                  setChatFilter(value)
                  setPage(1)
                }}
              >
                <SelectTrigger className={cn(behaviorSelectTriggerClass, 'sm:max-w-[11rem]')}>
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

            <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                  <CheckCircle2 className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">启用状态</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentEnabledFilterLabel}
                  </span>
                </span>
              </span>
              <Select
                value={enabledFilter}
                onValueChange={(value) => {
                  setEnabledFilter(value as EnabledFilter)
                  setPage(1)
                }}
              >
                <SelectTrigger className={cn(behaviorSelectTriggerClass, 'sm:max-w-[8rem]')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="enabled">启用</SelectItem>
                  <SelectItem value="disabled">停用</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                  <Users className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">行为主体</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentActorFilterLabel}
                  </span>
                </span>
              </span>
              <Select
                value={actorFilter}
                onValueChange={(value) => {
                  setActorFilter(value as ActorFilter)
                  setPage(1)
                }}
              >
                <SelectTrigger className={cn(behaviorSelectTriggerClass, 'sm:max-w-[9rem]')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部主体</SelectItem>
                  {ACTOR_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ios-row min-h-[64px] flex-col !items-stretch !justify-start gap-2 py-3 sm:flex-row sm:!items-center sm:!justify-between">
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                  <BrainCircuit className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">学习来源</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {currentLearningFilterLabel}
                  </span>
                </span>
              </span>
              <Select
                value={learningFilter}
                onValueChange={(value) => {
                  setLearningFilter(value as LearningFilter)
                  setPage(1)
                }}
              >
                <SelectTrigger className={cn(behaviorSelectTriggerClass, 'sm:max-w-[9rem]')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部来源</SelectItem>
                  {LEARNING_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div
              className={cn(
                'ios-row min-h-[68px] flex-col !items-stretch !justify-start gap-3 py-3 sm:flex-row sm:!items-center sm:!justify-between'
              )}
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                  <Hash className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[16px] font-normal leading-6">显示设置</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    每页 {pageSize} 条 · 已选 {selectedCount}
                  </span>
                </span>
              </span>
              <div className="flex w-full shrink-0 flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
                <Select
                  value={String(pageSize)}
                  onValueChange={(value) => {
                    setPageSize(Number(value))
                    setPage(1)
                    setSelectedIds(new Set())
                  }}
                >
                  <SelectTrigger className={cn(behaviorSelectTriggerClass, 'sm:max-w-[8rem]')}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[10, 20, 50, 100].map((size) => (
                      <SelectItem key={size} value={String(size)}>
                        {size} 条
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={refreshAll}
                  disabled={loading}
                  className="h-11 w-11 rounded-full"
                  title="刷新"
                >
                  <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
                </Button>
                {selectedCount > 0 && (
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
                      onClick={() => setBatchDeleteOpen(true)}
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

          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <p className="text-[13px] font-medium leading-5 text-muted-foreground">
                行为模式列表
              </p>
              {behaviors.length > 0 && (
                <button
                  type="button"
                  onClick={toggleSelectAll}
                  className="ios-touch min-h-11 rounded-full px-3.5 py-2 text-[13px] font-medium leading-5 text-primary hover:bg-accent/60"
                >
                  {selectedCount === behaviors.length ? '取消全选' : '全选'}
                </button>
              )}
            </div>
            <div className="ios-group overflow-hidden">
              {loading ? (
                <IosListSkeleton rows={4} />
              ) : behaviors.length === 0 ? (
                <div className="ios-empty-state">
                  <span className="ios-empty-illustration">
                    <BrainCircuit className="relative z-10 h-7 w-7 text-primary" />
                  </span>
                  <div>
                    <p className="text-[16px] font-semibold leading-6 text-foreground">
                      暂无行为模式
                    </p>
                    <p className="mt-1 max-w-sm text-[13px] leading-5">
                      学习或新增行为后，可以在这里管理引用范围、启用状态和来源片段。
                    </p>
                  </div>
                  <Button onClick={openCreateDialog} size="sm" className="h-11 px-5">
                    <Plus className="mr-1 h-4 w-4" />
                    新增行为
                  </Button>
                </div>
              ) : (
                behaviors.map((behavior) => {
                  const ActorIcon =
                    ACTOR_OPTIONS.find((option) => option.value === behavior.actor_type)?.icon ?? Users
                  const chatName = getChatName(behavior.chat_id)

                  return (
                    <div
                      key={behavior.id}
                      className={cn(
                        'ios-row min-h-[116px] flex-col !items-stretch !justify-start gap-3 py-3 sm:flex-row sm:!items-center sm:!justify-between',
                        !behavior.enabled && 'opacity-70'
                      )}
                    >
                      <div className="flex min-w-0 items-start gap-3">
                        <Checkbox
                          checked={selectedIds.has(behavior.id)}
                          onCheckedChange={(checked) =>
                            toggleSelection(behavior.id, checked === true)
                          }
                          className="mt-2"
                        />
                        <span className="ios-symbol ios-symbol-sm ios-symbol-purple mt-0.5">
                          <ActorIcon className="h-4 w-4" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={behavior.enabled ? 'default' : 'outline'}>
                              {behavior.enabled ? '启用' : '停用'}
                            </Badge>
                            <Badge variant="secondary">{actorLabel(behavior.actor_type)}</Badge>
                            <Badge variant="secondary">
                              {learningLabel(behavior.learning_type)}
                            </Badge>
                            <span
                              className="max-w-[14rem] truncate rounded-full bg-muted px-2.5 py-1 text-[12px] font-medium leading-4 text-muted-foreground"
                              title={chatName}
                            >
                              {chatName}
                            </span>
                          </div>
                          <h3
                            className="mt-2 line-clamp-1 text-[15px] font-semibold leading-5 text-foreground"
                            title={behavior.action}
                          >
                            {behavior.action}
                          </h3>
                          <p
                            className="mt-1 line-clamp-2 text-[13px] leading-5 text-muted-foreground"
                            title={behavior.outcome}
                          >
                            {behavior.outcome}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] leading-4 text-muted-foreground">
                            <span className="rounded-full bg-muted px-2.5 py-1">
                              {behavior.count} 次
                            </span>
                            <span className="rounded-full bg-muted px-2.5 py-1">
                              评分 {behavior.score.toFixed(1)}
                            </span>
                            <span className="rounded-full bg-muted px-2.5 py-1">
                              命中 {behavior.selected_count}
                            </span>
                            <span className="inline-flex min-w-0 items-center gap-1 rounded-full bg-muted px-2.5 py-1">
                              <Clock className="h-3 w-3 shrink-0" />
                              <span className="truncate">{formatTime(behavior.last_active_time)}</span>
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center justify-end gap-2 pl-14 sm:pl-0">
                        <Switch
                          checked={behavior.enabled}
                          onCheckedChange={(checked) => handleToggleEnabled(behavior, checked)}
                          aria-label="启用行为模式"
                        />
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
                                className={behaviorActionClass}
                                onClick={() => openEditDialog(behavior)}
                              >
                                <span className={cn(behaviorActionIconClass, 'ios-symbol-purple')}>
                                  <Edit className="h-[18px] w-[18px]" />
                                </span>
                                编辑
                              </button>
                              <button
                                type="button"
                                className={behaviorActionClass}
                                onClick={() => openDetailDialog(behavior)}
                              >
                                <span className={cn(behaviorActionIconClass, 'ios-symbol-blue')}>
                                  <Eye className="h-[18px] w-[18px]" />
                                </span>
                                详情
                              </button>
                              <button
                                type="button"
                                className={cn(behaviorActionClass, 'text-destructive')}
                                onClick={() => setDeleteConfirmBehavior(behavior)}
                              >
                                <span className={cn(behaviorActionIconClass, 'ios-symbol-red')}>
                                  <Trash2 className="h-[18px] w-[18px]" />
                                </span>
                                删除
                              </button>
                            </div>
                          </PopoverContent>
                        </Popover>
                      </div>
                    </div>
                  )
                })
              )}

              {total > 0 && (
                <div className="ios-row ios-row-plain min-h-[68px] flex-col !items-stretch !justify-start gap-3 border-t border-border/60 sm:flex-row sm:!items-center sm:!justify-between">
                  <div className="text-sm text-muted-foreground">
                    共 {total} 条记录，第 {page} / {totalPages} 页
                  </div>
                  <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setPage(1)}
                      disabled={page === 1}
                      className="hidden h-11 w-11 rounded-full sm:inline-flex"
                      title="第一页"
                    >
                      <ChevronsLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage((current) => Math.max(1, current - 1))}
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
                        onChange={(event) => setJumpToPage(event.target.value)}
                        onKeyDown={(event) => event.key === 'Enter' && handleJumpToPage()}
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
                      onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
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
                      title="最后一页"
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

      <Dialog
        open={formMode !== null}
        onOpenChange={(open) => {
          if (!open) {
            setFormMode(null)
            setEditingBehavior(null)
          }
        }}
      >
        <DialogContent className="max-h-[92vh] overflow-hidden p-0 sm:max-w-3xl">
          <DialogHeader className="px-6 pb-3 pt-6">
            <DialogTitle>{formMode === 'create' ? '新增行为模式' : '编辑行为模式'}</DialogTitle>
            <DialogDescription>调整行为模式的匹配范围、行为描述和启用状态</DialogDescription>
          </DialogHeader>
          <ScrollArea className="max-h-[68vh] px-6">
            <div className="space-y-5 pb-6">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label>聊天 ID</Label>
                  {formChatOptions.length > 0 ? (
                    <Select
                      value={form.chat_id}
                      onValueChange={(value) => setForm((current) => ({ ...current, chat_id: value }))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="选择聊天" />
                      </SelectTrigger>
                      <SelectContent>
                        {formChatOptions.map((chat) => (
                          <SelectItem key={chat.chat_id} value={chat.chat_id}>
                            {chat.chat_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      value={form.chat_id}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, chat_id: event.target.value }))
                      }
                      placeholder="例如 qq:123456:group"
                    />
                  )}
                </div>
                <div className="grid gap-2">
                  <Label>启用状态</Label>
                  <div className="flex min-h-11 items-center justify-between rounded-[14px] bg-muted/60 px-3">
                    <span className="text-sm text-muted-foreground">
                      {form.enabled ? '启用' : '停用'}
                    </span>
                    <Switch
                      checked={form.enabled}
                      onCheckedChange={(checked) =>
                        setForm((current) => ({ ...current, enabled: checked }))
                      }
                    />
                  </div>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label>行为主体</Label>
                  <Select
                    value={form.actor_type}
                    onValueChange={(value) =>
                      setForm((current) => ({
                        ...current,
                        actor_type: value as BehaviorActorType,
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ACTOR_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label>学习来源</Label>
                  <Select
                    value={form.learning_type}
                    onValueChange={(value) =>
                      setForm((current) => ({
                        ...current,
                        learning_type: value as BehaviorLearningType,
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LEARNING_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label>计数</Label>
                  <Input
                    type="number"
                    min={1}
                    value={form.count}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, count: Number(event.target.value) }))
                    }
                  />
                </div>
                <div className="grid gap-2">
                  <Label>评分</Label>
                  <Input
                    type="number"
                    min={0}
                    max={5}
                    step={0.1}
                    value={form.score}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, score: Number(event.target.value) }))
                    }
                  />
                </div>
              </div>

              <div className="grid gap-2">
                <Label>行为</Label>
                <Textarea
                  value={form.action}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, action: event.target.value }))
                  }
                  placeholder="例如：先确认对方的关键诉求，再给出简短建议"
                />
              </div>

              <div className="grid gap-2">
                <Label>结果</Label>
                <Textarea
                  value={form.outcome}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, outcome: event.target.value }))
                  }
                  placeholder="例如：对方继续补充上下文，聊天节奏更顺"
                />
              </div>

              <div className="grid gap-2">
                <Label>来源片段</Label>
                <Textarea
                  value={form.source_text}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, source_text: event.target.value }))
                  }
                  placeholder="可选，记录学习来源的聊天片段"
                />
              </div>

              <div className="grid gap-2">
                <Label>来源消息 ID</Label>
                <Textarea
                  value={form.source_ids}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, source_ids: event.target.value }))
                  }
                  placeholder="每行一个，或用逗号分隔"
                  className="min-h-[84px] font-mono text-sm"
                />
              </div>
            </div>
          </ScrollArea>
          <DialogFooter className="border-t border-border/50 px-6 py-4">
            <Button variant="outline" onClick={() => setFormMode(null)} disabled={saving}>
              取消
            </Button>
            <Button onClick={handleSubmitForm} disabled={saving}>
              {saving ? '保存中' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={detailBehavior !== null} onOpenChange={(open) => !open && setDetailBehavior(null)}>
        <DialogContent className="max-h-[92vh] overflow-hidden p-0 sm:max-w-3xl">
          <DialogHeader className="px-6 pb-3 pt-6">
            <DialogTitle>行为模式详情</DialogTitle>
            <DialogDescription>ID {detailBehavior?.id}</DialogDescription>
          </DialogHeader>
          {detailBehavior && (
            <ScrollArea className="max-h-[72vh] px-6 pb-6">
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Badge variant={detailBehavior.enabled ? 'default' : 'outline'}>
                    {detailBehavior.enabled ? '启用' : '停用'}
                  </Badge>
                  <Badge variant="secondary">{actorLabel(detailBehavior.actor_type)}</Badge>
                  <Badge variant="secondary">{learningLabel(detailBehavior.learning_type)}</Badge>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <DetailItem
                    label="聊天"
                    value={chatNameMap.get(detailBehavior.chat_id) ?? detailBehavior.chat_id}
                  />
                  <DetailItem label="聊天 ID" value={detailBehavior.chat_id} mono />
                  <DetailItem label="计数" value={String(detailBehavior.count)} />
                  <DetailItem label="评分" value={detailBehavior.score.toFixed(2)} />
                  <DetailItem label="命中次数" value={String(detailBehavior.selected_count)} />
                  <DetailItem label="最后命中" value={formatTime(detailBehavior.last_selected_time)} />
                  <DetailItem label="最后活跃" value={formatTime(detailBehavior.last_active_time)} />
                  <DetailItem label="创建时间" value={formatTime(detailBehavior.create_date)} />
                </div>

                <DetailBlock label="行为" value={detailBehavior.action} />
                <DetailBlock label="结果" value={detailBehavior.outcome} />
                <DetailBlock label="来源片段" value={detailBehavior.source_text || '暂无'} />
                <DetailBlock
                  label="来源消息 ID"
                  value={detailBehavior.source_ids.length > 0 ? detailBehavior.source_ids.join('\n') : '暂无'}
                  mono
                />
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleteConfirmBehavior !== null}
        onOpenChange={(open) => !open && setDeleteConfirmBehavior(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除这个行为模式吗？此操作无法撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={batchDeleteOpen} onOpenChange={setBatchDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认批量删除</AlertDialogTitle>
            <AlertDialogDescription>
              将删除已选择的 {selectedCount} 个行为模式，此操作无法撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleBatchDelete}>删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function DetailItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-[16px] bg-muted/35 p-3">
      <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
      <div className={cn('break-words text-sm', mono && 'font-mono')}>{value}</div>
    </div>
  )
}

function DetailBlock({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-[16px] bg-muted/35 p-3">
      <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
      <div className={cn('whitespace-pre-wrap break-words text-sm leading-relaxed', mono && 'font-mono')}>
        {value}
      </div>
    </div>
  )
}
