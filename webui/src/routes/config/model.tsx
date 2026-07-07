import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Check,
  ChevronRight,
  ChevronsUpDown,
  CircleHelp,
  Cpu,
  Info,
  Loader2,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { getModelConfig, updateModelConfig } from '@/lib/config-api'
import { restartRiyaBot } from '@/lib/system-api'
import { useToast } from '@/hooks/use-toast'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { RestartingOverlay } from '@/components/RestartingOverlay'
import { KeyValueEditor } from '@/components/ui/key-value-editor'

// 导入模块化的类型定义和组件
import type { ModelInfo, ProviderConfig, ModelTaskConfig, TaskConfig } from './model/types'
import { TaskConfigCard, Pagination, ModelTable, ModelCardList } from './model/components'
import { useModelTour, useModelFetcher, useModelAutoSave } from './model/hooks'

type ModelConfigTab = 'models' | 'tasks'

type ModelConfigTabItem = {
  value: ModelConfigTab
  label: string
  description: string
  Icon: LucideIcon
  color: string
}

const MODEL_CONFIG_TABS: ModelConfigTabItem[] = [
  {
    value: 'models',
    label: '添加模型',
    description: '配置可用模型列表',
    Icon: Cpu,
    color: 'ios-symbol-blue',
  },
  {
    value: 'tasks',
    label: '分配功能',
    description: '为任务选择模型',
    Icon: SlidersHorizontal,
    color: 'ios-symbol-purple',
  },
]

export function ModelConfigPage() {
  const DEFAULT_TASK: TaskConfig = {
    model_list: [],
    max_tokens: 1024,
    temperature: 0.3,
    slow_threshold: 15,
  }
  const [models, setModels] = useState<ModelInfo[]>([])
  const [providers, setProviders] = useState<string[]>([])
  const [providerConfigs, setProviderConfigs] = useState<ProviderConfig[]>([])
  const [modelNames, setModelNames] = useState<string[]>([])
  const [taskConfig, setTaskConfig] = useState<ModelTaskConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [autoSaving, setAutoSaving] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [showRestartOverlay, setShowRestartOverlay] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingModel, setEditingModel] = useState<ModelInfo | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedModels, setSelectedModels] = useState<Set<number>>(new Set())
  const [batchDeleteDialogOpen, setBatchDeleteDialogOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [jumpToPage, setJumpToPage] = useState('')
  const [activeView, setActiveView] = useState<ModelConfigTab>('models')
  const [viewDialogOpen, setViewDialogOpen] = useState(false)
  const activeViewItem =
    MODEL_CONFIG_TABS.find((item) => item.value === activeView) ?? MODEL_CONFIG_TABS[0]

  // 模型 Combobox 状态
  const [modelComboboxOpen, setModelComboboxOpen] = useState(false)

  // 表单验证错误状态
  const [formErrors, setFormErrors] = useState<{
    name?: string
    api_provider?: string
    model_identifier?: string
  }>({})

  const { toast } = useToast()

  // Tour 引导 (使用 hook 封装的逻辑)
  const { startTour, isRunning: tourIsRunning } = useModelTour({
    onCloseEditDialog: () => setEditDialogOpen(false),
  })

  // 自动保存 (使用 hook 封装的逻辑)
  const { clearTimers: clearAutoSaveTimers, initialLoadRef } = useModelAutoSave({
    models,
    taskConfig,
    onSavingChange: setAutoSaving,
    onUnsavedChange: setHasUnsavedChanges,
  })

  // 加载配置
  const loadConfig = useCallback(async () => {
    try {
      setLoading(true)
      const config = await getModelConfig()
      const modelList = (config.models as ModelInfo[]) || []
      setModels(modelList)
      setModelNames(modelList.map((m) => m.name))

      const providerList = (config.api_providers as ProviderConfig[]) || []
      setProviders(providerList.map((p) => p.name))
      setProviderConfigs(providerList)

      const rawTaskConfig = (config.model_task_config as Record<string, unknown> | null) || null
      if (rawTaskConfig) {
        setTaskConfig({
          ...rawTaskConfig,
          utils: rawTaskConfig.utils || { ...DEFAULT_TASK },
          utils_small: rawTaskConfig.utils_small || { ...DEFAULT_TASK },
          tool_use: rawTaskConfig.tool_use || { ...DEFAULT_TASK },
          replyer: rawTaskConfig.replyer || { ...DEFAULT_TASK },
          planner: rawTaskConfig.planner || { ...DEFAULT_TASK },
          vlm: rawTaskConfig.vlm || { ...DEFAULT_TASK },
          voice: rawTaskConfig.voice || { ...DEFAULT_TASK },
          embedding: rawTaskConfig.embedding || { ...DEFAULT_TASK },
          memory_encoder: rawTaskConfig.memory_encoder || { ...DEFAULT_TASK },
          memory_weaver: rawTaskConfig.memory_weaver || { ...DEFAULT_TASK },
        } as ModelTaskConfig)
      } else {
        setTaskConfig(null)
      }
      setHasUnsavedChanges(false)
      initialLoadRef.current = false
    } catch (error) {
      console.error('加载配置失败:', error)
    } finally {
      setLoading(false)
    }
  }, [initialLoadRef])

  // 初始加载
  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  // 获取指定提供商的配置
  const getProviderConfig = useCallback(
    (providerName: string): ProviderConfig | undefined => {
      return providerConfigs.find((p) => p.name === providerName)
    },
    [providerConfigs]
  )

  // 模型列表获取 (使用 hook 封装的逻辑)
  const {
    availableModels,
    fetchingModels,
    modelFetchError,
    matchedTemplate,
    fetchModelsForProvider,
    clearModels,
  } = useModelFetcher({ getProviderConfig })

  // 当选择的提供商变化时，获取模型列表
  useEffect(() => {
    if (editDialogOpen && editingModel?.api_provider) {
      fetchModelsForProvider(editingModel.api_provider)
    }
  }, [editDialogOpen, editingModel?.api_provider, fetchModelsForProvider])

  // 重启主程序
  const handleRestart = async () => {
    try {
      setRestarting(true)
      // 发送重启请求（不等待响应，因为服务器会立即关闭）
      restartRiyaBot().catch(() => {
        // 忽略网络错误，这是预期行为
      })
      // 立即显示遮罩层并开始状态检测
      setShowRestartOverlay(true)
    } catch (error) {
      console.error('重启失败:', error)
      setShowRestartOverlay(false)
      toast({
        title: '重启失败',
        description: '无法发送重启请求，请手动重启',
        variant: 'destructive',
      })
      setRestarting(false)
    }
  }

  // 清理模型中的 null 值（TOML 不支持 null）
  const cleanModelForSave = (model: ModelInfo): ModelInfo => {
    const cleaned: ModelInfo = {
      model_identifier: model.model_identifier,
      name: model.name,
      api_provider: model.api_provider,
      price_in: model.price_in ?? 0,
      price_out: model.price_out ?? 0,
      force_stream_mode: model.force_stream_mode ?? false,
      extra_params: model.extra_params ?? {},
    }
    // 只有在有值时才添加可选字段
    if (model.temperature != null) {
      cleaned.temperature = model.temperature
    }
    if (model.max_tokens != null) {
      cleaned.max_tokens = model.max_tokens
    }
    return cleaned
  }

  // 保存并重启
  const handleSaveAndRestart = async () => {
    try {
      setSaving(true)
      clearAutoSaveTimers()
      const config = await getModelConfig()
      // 清理每个模型中的 null 值
      config.models = models.map(cleanModelForSave)
      config.model_task_config = taskConfig
      await updateModelConfig(config)
      setHasUnsavedChanges(false)
      toast({
        title: '保存成功',
        description: '正在重启主程序...',
      })
      await handleRestart()
    } catch (error) {
      console.error('保存配置失败:', error)
      toast({
        title: '保存失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
      setSaving(false)
    }
  }

  // 重启完成回调
  const handleRestartComplete = () => {
    // 清除token，避免自动登录
    localStorage.removeItem('access-token')
    window.location.href = '/auth'
  }

  // 重启失败回调
  const handleRestartFailed = () => {
    setShowRestartOverlay(false)
    setRestarting(false)
    toast({
      title: '重启超时',
      description: '服务未能在预期时间内恢复，请手动检查或刷新页面',
      variant: 'destructive',
    })
  }

  // 保存配置（手动保存）
  const saveConfig = async () => {
    try {
      setSaving(true)

      // 先取消自动保存定时器
      clearAutoSaveTimers()

      const config = await getModelConfig()
      // 清理每个模型中的 null 值
      config.models = models.map(cleanModelForSave)
      config.model_task_config = taskConfig
      await updateModelConfig(config)
      setHasUnsavedChanges(false)
      toast({
        title: '保存成功',
        description: '模型配置已保存',
      })
      await loadConfig() // 重新加载以更新模型名称列表
    } catch (error) {
      console.error('保存配置失败:', error)
      toast({
        title: '保存失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  // 打开编辑对话框
  const openEditDialog = (model: ModelInfo | null, index: number | null) => {
    // 清除表单验证错误
    setFormErrors({})

    setEditingModel(
      model || {
        model_identifier: '',
        name: '',
        api_provider: providers[0] || '',
        price_in: 0,
        price_out: 0,
        temperature: null,
        max_tokens: null,
        force_stream_mode: false,
        extra_params: {},
      }
    )
    setEditingIndex(index)
    setEditDialogOpen(true)
  }

  // 保存编辑
  const handleSaveEdit = () => {
    if (!editingModel) return

    // 验证必填项
    const errors: { name?: string; api_provider?: string; model_identifier?: string } = {}
    if (!editingModel.name?.trim()) {
      errors.name = '请输入模型名称'
    }
    if (!editingModel.api_provider?.trim()) {
      errors.api_provider = '请选择 API 提供商'
    }
    if (!editingModel.model_identifier?.trim()) {
      errors.model_identifier = '请输入模型标识符'
    }

    if (Object.keys(errors).length > 0) {
      setFormErrors(errors)
      return
    }

    // 清除错误状态
    setFormErrors({})

    // 填充空值的默认值，并移除 null 值的可选字段（TOML 不支持 null）
    const modelToSave: ModelInfo = {
      model_identifier: editingModel.model_identifier,
      name: editingModel.name,
      api_provider: editingModel.api_provider,
      price_in: editingModel.price_in ?? 0,
      price_out: editingModel.price_out ?? 0,
      force_stream_mode: editingModel.force_stream_mode ?? false,
      extra_params: editingModel.extra_params ?? {},
    }

    // 只有在有值时才添加可选字段
    if (editingModel.temperature != null) {
      modelToSave.temperature = editingModel.temperature
    }
    if (editingModel.max_tokens != null) {
      modelToSave.max_tokens = editingModel.max_tokens
    }

    let newModels: ModelInfo[]
    let oldModelName: string | null = null

    if (editingIndex !== null) {
      // 记录旧的模型名称，用于更新任务配置
      oldModelName = models[editingIndex].name
      newModels = [...models]
      newModels[editingIndex] = modelToSave
    } else {
      newModels = [...models, modelToSave]
    }

    setModels(newModels)
    // 立即更新模型名称列表
    setModelNames(newModels.map((m) => m.name))

    // 如果模型名称发生变化，更新任务配置中对该模型的引用
    if (oldModelName && oldModelName !== modelToSave.name && taskConfig) {
      const updateModelList = (list: string[]): string[] => {
        return list.map((name) => (name === oldModelName ? modelToSave.name : name))
      }

      setTaskConfig({
        ...taskConfig,
        utils: {
          ...taskConfig.utils,
          model_list: updateModelList(taskConfig.utils?.model_list || []),
        },
        utils_small: {
          ...taskConfig.utils_small,
          model_list: updateModelList(taskConfig.utils_small?.model_list || []),
        },
        tool_use: {
          ...taskConfig.tool_use,
          model_list: updateModelList(taskConfig.tool_use?.model_list || []),
        },
        replyer: {
          ...taskConfig.replyer,
          model_list: updateModelList(taskConfig.replyer?.model_list || []),
        },
        planner: {
          ...taskConfig.planner,
          model_list: updateModelList(taskConfig.planner?.model_list || []),
        },
        vlm: { ...taskConfig.vlm, model_list: updateModelList(taskConfig.vlm?.model_list || []) },
        voice: {
          ...taskConfig.voice,
          model_list: updateModelList(taskConfig.voice?.model_list || []),
        },
        embedding: {
          ...taskConfig.embedding,
          model_list: updateModelList(taskConfig.embedding?.model_list || []),
        },
        memory_encoder: {
          ...(taskConfig.memory_encoder || {}),
          model_list: updateModelList(taskConfig.memory_encoder?.model_list || []),
        },
        memory_weaver: {
          ...(taskConfig.memory_weaver || {}),
          model_list: updateModelList(taskConfig.memory_weaver?.model_list || []),
        },
      })
    }

    setEditDialogOpen(false)
    setEditingModel(null)
    setEditingIndex(null)
  }

  // 处理编辑对话框关闭
  const handleEditDialogClose = (open: boolean) => {
    if (!open && editingModel) {
      // 关闭时填充默认值
      const updatedModel = {
        ...editingModel,
        price_in: editingModel.price_in ?? 0,
        price_out: editingModel.price_out ?? 0,
      }
      setEditingModel(updatedModel)
    }
    setEditDialogOpen(open)
  }

  // 打开删除确认对话框
  const openDeleteDialog = (index: number) => {
    setDeletingIndex(index)
    setDeleteDialogOpen(true)
  }

  // 确认删除模型
  const handleConfirmDelete = () => {
    if (deletingIndex !== null) {
      const newModels = models.filter((_, i) => i !== deletingIndex)
      setModels(newModels)
      // 立即更新模型名称列表
      setModelNames(newModels.map((m) => m.name))
      setSelectedModels(new Set())
      toast({
        title: '删除成功',
        description: '模型已从列表中移除',
      })
    }
    setDeleteDialogOpen(false)
    setDeletingIndex(null)
  }

  // 切换单个模型选择
  const toggleModelSelection = (index: number) => {
    const newSelected = new Set(selectedModels)
    if (newSelected.has(index)) {
      newSelected.delete(index)
    } else {
      newSelected.add(index)
    }
    setSelectedModels(newSelected)
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedModels.size === filteredModels.length) {
      setSelectedModels(new Set())
    } else {
      const allIndices = filteredModels.map((_, idx) =>
        models.findIndex((m) => m === filteredModels[idx])
      )
      setSelectedModels(new Set(allIndices))
    }
  }

  // 打开批量删除确认对话框
  const openBatchDeleteDialog = () => {
    if (selectedModels.size === 0) {
      toast({
        title: '提示',
        description: '请先选择要删除的模型',
        variant: 'default',
      })
      return
    }
    setBatchDeleteDialogOpen(true)
  }

  // 确认批量删除
  const handleConfirmBatchDelete = () => {
    const newModels = models.filter((_, index) => !selectedModels.has(index))
    setModels(newModels)
    // 立即更新模型名称列表
    setModelNames(newModels.map((m) => m.name))
    setSelectedModels(new Set())
    setBatchDeleteDialogOpen(false)
    toast({
      title: '批量删除成功',
      description: `已删除 ${selectedModels.size} 个模型`,
    })
  }

  // 更新任务配置
  const updateTaskConfig = (
    taskName: keyof ModelTaskConfig,
    field: keyof TaskConfig,
    value: string[] | number
  ) => {
    if (!taskConfig) return
    setTaskConfig({
      ...taskConfig,
      [taskName]: {
        ...taskConfig[taskName],
        [field]: value,
      },
    })
  }

  // 过滤模型列表
  const filteredModels = models.filter((model) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      model.name.toLowerCase().includes(query) ||
      model.model_identifier.toLowerCase().includes(query) ||
      model.api_provider.toLowerCase().includes(query)
    )
  })

  // 分页逻辑
  const totalPages = Math.ceil(filteredModels.length / pageSize)
  const paginatedModels = filteredModels.slice((page - 1) * pageSize, page * pageSize)

  // 页码跳转
  const handleJumpToPage = () => {
    const targetPage = parseInt(jumpToPage)
    if (targetPage >= 1 && targetPage <= totalPages) {
      setPage(targetPage)
      setJumpToPage('')
    }
  }

  // 检查模型是否被任务使用
  const isModelUsed = (modelName: string): boolean => {
    if (!taskConfig) return false

    const allTaskLists = [
      taskConfig.utils?.model_list || [],
      taskConfig.utils_small?.model_list || [],
      taskConfig.tool_use?.model_list || [],
      taskConfig.replyer?.model_list || [],
      taskConfig.planner?.model_list || [],
      taskConfig.vlm?.model_list || [],
      taskConfig.voice?.model_list || [],
      taskConfig.embedding?.model_list || [],
      taskConfig.memory_encoder?.model_list || [],
      taskConfig.memory_weaver?.model_list || [],
    ]

    return allTaskLists.some((list) => list.includes(modelName))
  }

  const saveLabel = saving
    ? '保存中...'
    : autoSaving
      ? '自动保存中...'
      : hasUnsavedChanges
        ? '保存配置'
        : '已保存'
  const restartLabel = restarting ? '重启中...' : hasUnsavedChanges ? '保存并重启' : '重启主程序'
  const saveDescription = hasUnsavedChanges ? '有更改等待写入配置' : '当前配置已写入'

  if (loading) {
    return (
      <ScrollArea className="h-full">
        <div className="ios-page">
          <div className="ios-content">
            <div className="space-y-2 px-1">
              <Skeleton className="h-9 w-56 rounded-[12px]" />
              <Skeleton className="h-5 w-44 rounded-[10px]" />
            </div>
            <div className="ios-group overflow-hidden p-4 sm:p-5">
              <div className="flex items-center justify-between gap-4">
                <div className="space-y-2">
                  <Skeleton className="h-5 w-28 rounded-[10px]" />
                  <Skeleton className="h-4 w-40 rounded-[9px]" />
                </div>
                <Skeleton className="h-9 w-24 rounded-full" />
              </div>
              <div className="mt-5 space-y-3">
                {[0, 1, 2].map((item) => (
                  <div key={item} className="flex min-h-[70px] items-center gap-3">
                    <Skeleton className="h-9 w-9 shrink-0 rounded-[10px]" />
                    <div className="min-w-0 flex-1 space-y-2">
                      <Skeleton className="h-4 w-2/5 rounded-[8px]" />
                      <Skeleton className="h-3.5 w-3/5 rounded-[8px]" />
                    </div>
                    <Skeleton className="h-7 w-16 rounded-full" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </ScrollArea>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="ios-page space-y-5 sm:space-y-6">
        {/* 页面标题 */}
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">模型管理与分配</h1>
            <p className="ios-subtitle">添加模型并为模型分配功能</p>
          </div>
          <div className="hidden w-full grid-cols-[2.75rem_minmax(0,1fr)] gap-2 sm:flex sm:w-auto">
            <Button
              onClick={startTour}
              disabled={tourIsRunning}
              size="sm"
              variant="outline"
              className="h-11 w-11 px-0 sm:h-9 sm:w-auto sm:min-w-[112px] sm:px-4"
              aria-label="启动配置引导"
              title="启动配置引导"
            >
              <CircleHelp className="h-4 w-4 sm:mr-2" strokeWidth={2} fill="none" />
              <span className="hidden sm:inline">{tourIsRunning ? '引导中' : '配置引导'}</span>
            </Button>
            <Button
              onClick={saveConfig}
              disabled={saving || autoSaving || !hasUnsavedChanges || restarting}
              size="sm"
              variant="outline"
              className="h-11 w-11 px-0 sm:h-9 sm:w-auto sm:min-w-[120px] sm:px-4"
              aria-label={
                saving
                  ? '保存中'
                  : autoSaving
                    ? '自动保存中'
                    : hasUnsavedChanges
                      ? '保存配置'
                      : '已保存'
              }
              title={
                saving
                  ? '保存中...'
                  : autoSaving
                    ? '自动保存中...'
                    : hasUnsavedChanges
                      ? '保存配置'
                      : '已保存'
              }
            >
              <Save className="h-4 w-4 sm:mr-2" strokeWidth={2} fill="none" />
              <span className="hidden sm:inline">{saveLabel}</span>
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  disabled={saving || autoSaving || restarting}
                  size="sm"
                  className="h-11 min-w-0 px-4 sm:h-9 sm:w-auto sm:min-w-[120px]"
                  aria-label={restartLabel}
                  title={restartLabel}
                >
                  <Power className="mr-2 h-4 w-4" />
                  <span className="truncate">{restartLabel}</span>
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>确认重启主程序？</AlertDialogTitle>
                  <AlertDialogDescription asChild>
                    <div>
                      <p>
                        {hasUnsavedChanges
                          ? '当前有未保存的配置更改。点击确认将先保存配置,然后重启主程序使新配置生效。重启过程中服务将暂时离线。'
                          : '即将重启主程序。重启过程中服务将暂时离线,配置将在重启后生效。'}
                      </p>
                    </div>
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={hasUnsavedChanges ? handleSaveAndRestart : handleRestart}
                  >
                    {hasUnsavedChanges ? '保存并重启' : '确认重启'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>

        <div className="ios-group overflow-hidden sm:hidden">
          <button
            type="button"
            onClick={saveConfig}
            disabled={saving || autoSaving || !hasUnsavedChanges || restarting}
            className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-60"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                <Save className="h-4 w-4" strokeWidth={2} fill="none" />
              </span>
              <span className="min-w-0">
                <span className="block text-[15px] font-medium leading-5">{saveLabel}</span>
                <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                  {saveDescription}
                </span>
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
          </button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button
                type="button"
                disabled={saving || autoSaving || restarting}
                className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-60"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                    <Power className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">{restartLabel}</span>
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>确认重启主程序？</AlertDialogTitle>
                <AlertDialogDescription asChild>
                  <div>
                    <p>
                      {hasUnsavedChanges
                        ? '当前有未保存的配置更改。点击确认将先保存配置,然后重启主程序使新配置生效。重启过程中服务将暂时离线。'
                        : '即将重启主程序。重启过程中服务将暂时离线,配置将在重启后生效。'}
                    </p>
                  </div>
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction
                  onClick={hasUnsavedChanges ? handleSaveAndRestart : handleRestart}
                >
                  {hasUnsavedChanges ? '保存并重启' : '确认重启'}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <button
            type="button"
            onClick={startTour}
            disabled={tourIsRunning}
            className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-60"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                <CircleHelp className="h-4 w-4" strokeWidth={2} fill="none" />
              </span>
              <span className="min-w-0">
                <span className="block text-[15px] font-medium leading-5">
                  {tourIsRunning ? '引导进行中' : '配置引导'}
                </span>
                <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                  逐步配置提供商、模型和任务分配
                </span>
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
          </button>
        </div>
        <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
          <DialogTrigger asChild>
            <button
              type="button"
              className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left sm:hidden"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className={`ios-symbol ios-symbol-sm ${activeViewItem.color}`}>
                  <activeViewItem.Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[15px] font-medium leading-5 text-foreground">
                    当前视图
                  </span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {activeViewItem.label} · {activeViewItem.description}
                  </span>
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </button>
          </DialogTrigger>
          <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
            <DialogHeader className="px-5 pb-1 pt-5">
              <DialogTitle>模型配置视图</DialogTitle>
              <DialogDescription>选择要管理的模型配置</DialogDescription>
            </DialogHeader>
            <div className="px-5 pb-5">
              <div className="ios-group overflow-hidden">
                {MODEL_CONFIG_TABS.map((item) => {
                  const selected = item.value === activeView
                  return (
                    <button
                      key={item.value}
                      type="button"
                      className="ios-touch flex min-h-[62px] w-full items-center justify-between gap-3 border-b border-border/70 px-4 py-3 text-left last:border-b-0 hover:bg-accent/55"
                      aria-current={selected ? 'page' : undefined}
                      onClick={() => {
                        setActiveView(item.value)
                        setViewDialogOpen(false)
                      }}
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span className={`ios-symbol ios-symbol-sm ${item.color}`}>
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

        {/* 标签页 */}
        <Tabs
          value={activeView}
          onValueChange={(value) => setActiveView(value as ModelConfigTab)}
          className="w-full space-y-1"
        >
          <TabsList className="hidden h-auto w-fit max-w-full grid-cols-2 gap-1 rounded-[16px] p-1 sm:inline-grid">
            <TabsTrigger value="models">添加模型</TabsTrigger>
            <TabsTrigger value="tasks" data-tour="tasks-tab-trigger">
              为模型分配功能
            </TabsTrigger>
          </TabsList>
          {/* 模型配置标签页 */}
          <TabsContent value="models" className="mt-5 space-y-5 sm:mt-6">
            <div className="hidden items-end justify-between gap-4 sm:flex">
              <div className="min-w-0">
                <p className="text-[15px] font-medium leading-5 text-foreground">可用模型</p>
                <p className="mt-1 text-sm leading-5 text-muted-foreground">配置可用的模型列表</p>
              </div>
              <div className="flex w-full gap-2 sm:w-auto">
                {selectedModels.size > 0 && (
                  <Button
                    onClick={openBatchDeleteDialog}
                    size="sm"
                    variant="destructive"
                    className="h-11 w-full sm:h-9 sm:w-auto"
                  >
                    <Trash2 className="mr-2 h-4 w-4" strokeWidth={2} fill="none" />
                    批量删除 ({selectedModels.size})
                  </Button>
                )}
                <Button
                  onClick={() => openEditDialog(null, null)}
                  size="sm"
                  variant="outline"
                  className="h-11 w-full sm:h-9 sm:w-auto"
                  data-tour="add-model-button"
                >
                  <Plus className="mr-2 h-4 w-4" strokeWidth={2} fill="none" />
                  添加模型
                </Button>
              </div>
            </div>

            <div className="space-y-3 sm:hidden">
              <p className="px-1 text-[13px] font-medium leading-5 text-muted-foreground">
                配置可用的模型列表
              </p>
              <div className="ios-group overflow-hidden">
                {selectedModels.size > 0 && (
                  <button
                    type="button"
                    onClick={openBatchDeleteDialog}
                    className="ios-row ios-touch text-destructive w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="ios-symbol ios-symbol-sm ios-symbol-red">
                        <Trash2 className="h-4 w-4" strokeWidth={2} fill="none" />
                      </span>
                      <span className="block truncate text-[15px] font-medium leading-5">
                        批量删除 ({selectedModels.size})
                      </span>
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => openEditDialog(null, null)}
                  className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                  data-tour="add-model-button"
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                      <Plus className="h-4 w-4" strokeWidth={2} fill="none" />
                    </span>
                    <span className="block truncate text-[15px] font-medium leading-5">
                      添加模型
                    </span>
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
                </button>
              </div>

              <div className="ios-group overflow-hidden px-4 py-3">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    placeholder="搜索模型"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="h-11 rounded-[12px] border-0 bg-muted pl-10 text-[16px] shadow-none focus-visible:ring-0"
                  />
                </div>
              </div>
              {searchQuery && (
                <p className="px-1 text-[13px] leading-5 text-muted-foreground">
                  找到 {filteredModels.length} 个结果
                </p>
              )}
            </div>

            {/* 搜索框 */}
            <div className="hidden items-center gap-3 sm:flex">
              <div className="relative w-full sm:max-w-sm sm:flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="搜索模型名称、标识符或提供商..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-10 rounded-[12px] border-0 bg-muted/75 pl-9 shadow-none focus-visible:ring-0"
                />
              </div>
              {searchQuery && (
                <p className="whitespace-nowrap text-sm text-muted-foreground">
                  找到 {filteredModels.length} 个结果
                </p>
              )}
            </div>

            {/* 模型列表 - 移动端卡片视图 */}
            <ModelCardList
              paginatedModels={paginatedModels}
              allModels={models}
              onEdit={openEditDialog}
              onDelete={openDeleteDialog}
              selectedModels={selectedModels}
              onToggleSelection={toggleModelSelection}
              isModelUsed={isModelUsed}
              searchQuery={searchQuery}
            />

            {/* 模型列表 - 桌面端表格视图 */}
            <ModelTable
              paginatedModels={paginatedModels}
              allModels={models}
              filteredModels={filteredModels}
              selectedModels={selectedModels}
              onEdit={openEditDialog}
              onDelete={openDeleteDialog}
              onToggleSelection={toggleModelSelection}
              onToggleSelectAll={toggleSelectAll}
              isModelUsed={isModelUsed}
              searchQuery={searchQuery}
            />

            {/* 分页 - 使用模块化组件 */}
            <Pagination
              page={page}
              pageSize={pageSize}
              totalItems={filteredModels.length}
              jumpToPage={jumpToPage}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              onJumpToPageChange={setJumpToPage}
              onJumpToPage={handleJumpToPage}
              onSelectionClear={() => setSelectedModels(new Set())}
            />
          </TabsContent>

          {/* 模型任务配置标签页 */}
          <TabsContent value="tasks" className="mt-5 space-y-6 sm:mt-6">
            <div className="px-1">
              <p className="text-[15px] font-medium leading-5 text-foreground">任务分配</p>
              <p className="mt-1 text-sm leading-5 text-muted-foreground">
                为不同的任务配置使用的模型和参数
              </p>
            </div>

            {taskConfig && (
              <div className="grid gap-4 sm:gap-6">
                {/* Utils 任务 */}
                <TaskConfigCard
                  title="组件模型 (utils)"
                  description="用于表情包、取名、关系、情绪变化等组件"
                  taskConfig={taskConfig.utils || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('utils', field, value)}
                  dataTour="task-model-select"
                />

                {/* Utils Small 任务 */}
                <TaskConfigCard
                  title="组件小模型 (utils_small)"
                  description="消耗量较大的组件，建议使用速度较快的小模型"
                  taskConfig={taskConfig.utils_small || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('utils_small', field, value)}
                />

                {/* Tool Use 任务 */}
                <TaskConfigCard
                  title="工具调用模型 (tool_use)"
                  description="需要使用支持工具调用的模型"
                  taskConfig={taskConfig.tool_use || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('tool_use', field, value)}
                />

                {/* Replyer 任务 */}
                <TaskConfigCard
                  title="首要回复模型 (replyer)"
                  description="用于表达器和表达方式学习"
                  taskConfig={taskConfig.replyer || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('replyer', field, value)}
                />

                {/* Planner 任务 */}
                <TaskConfigCard
                  title="决策模型 (planner)"
                  description="负责决定当前 Bot 该什么时候回复"
                  taskConfig={taskConfig.planner || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('planner', field, value)}
                />

                {/* VLM 任务 */}
                <TaskConfigCard
                  title="图像识别模型 (vlm)"
                  description="视觉语言模型"
                  taskConfig={taskConfig.vlm || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('vlm', field, value)}
                  hideTemperature
                />

                {/* Voice 任务 */}
                <TaskConfigCard
                  title="语音识别模型 (voice)"
                  description="语音转文字"
                  taskConfig={taskConfig.voice || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('voice', field, value)}
                  hideTemperature
                  hideMaxTokens
                />

                {/* Embedding 任务 */}
                <TaskConfigCard
                  title="嵌入模型 (embedding)"
                  description="用于向量化"
                  taskConfig={taskConfig.embedding || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('embedding', field, value)}
                  hideTemperature
                  hideMaxTokens
                />

                {/* Memory Encoder 任务 */}
                <TaskConfigCard
                  title="记忆编码模型 (memory_encoder)"
                  description="用于记忆系统的 LLM 编码（消息提取、结构化）"
                  taskConfig={taskConfig.memory_encoder || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('memory_encoder', field, value)}
                />

                {/* Memory Weaver 任务 */}
                <TaskConfigCard
                  title="梦境编织模型 (memory_weaver)"
                  description="用于梦境系统的洞察生成（跨域模式发现）"
                  taskConfig={taskConfig.memory_weaver || DEFAULT_TASK}
                  modelNames={modelNames}
                  onChange={(field, value) => updateTaskConfig('memory_weaver', field, value)}
                />
              </div>
            )}
          </TabsContent>
        </Tabs>

        {/* 编辑模型对话框 */}
        <Dialog open={editDialogOpen} onOpenChange={handleEditDialogClose}>
          <DialogContent
            className="max-h-[90vh] max-w-[95vw] overflow-y-auto sm:max-w-2xl"
            data-tour="model-dialog"
            preventOutsideClose={tourIsRunning}
          >
            <DialogHeader>
              <DialogTitle>{editingIndex !== null ? '编辑模型' : '添加模型'}</DialogTitle>
              <DialogDescription>配置模型的基本信息和参数</DialogDescription>
            </DialogHeader>

            <div className="grid gap-4 py-4">
              <div className="grid gap-2" data-tour="model-name-input">
                <Label htmlFor="model_name" className={formErrors.name ? 'text-destructive' : ''}>
                  模型名称 *
                </Label>
                <Input
                  id="model_name"
                  value={editingModel?.name || ''}
                  onChange={(e) => {
                    setEditingModel((prev) => (prev ? { ...prev, name: e.target.value } : null))
                    if (formErrors.name) {
                      setFormErrors((prev) => ({ ...prev, name: undefined }))
                    }
                  }}
                  placeholder="例如: qwen3-30b"
                  className={
                    formErrors.name ? 'border-destructive focus-visible:ring-destructive' : ''
                  }
                />
                {formErrors.name ? (
                  <p className="text-destructive text-xs">{formErrors.name}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">用于在任务配置中引用此模型</p>
                )}
              </div>

              <div className="grid gap-2" data-tour="model-provider-select">
                <Label
                  htmlFor="api_provider"
                  className={formErrors.api_provider ? 'text-destructive' : ''}
                >
                  API 提供商 *
                </Label>
                <Select
                  value={editingModel?.api_provider || ''}
                  onValueChange={(value) => {
                    setEditingModel((prev) => (prev ? { ...prev, api_provider: value } : null))
                    // 清空模型列表和错误状态，等待 useEffect 重新获取
                    clearModels()
                    if (formErrors.api_provider) {
                      setFormErrors((prev) => ({ ...prev, api_provider: undefined }))
                    }
                  }}
                >
                  <SelectTrigger
                    id="api_provider"
                    className={
                      formErrors.api_provider
                        ? 'border-destructive focus-visible:ring-destructive'
                        : ''
                    }
                  >
                    <SelectValue placeholder="选择提供商" />
                  </SelectTrigger>
                  <SelectContent>
                    {providers.map((provider) => (
                      <SelectItem key={provider} value={provider}>
                        {provider}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {formErrors.api_provider && (
                  <p className="text-destructive text-xs">{formErrors.api_provider}</p>
                )}
              </div>

              <div className="grid gap-2" data-tour="model-identifier-input">
                <div className="flex items-center justify-between">
                  <Label
                    htmlFor="model_identifier"
                    className={formErrors.model_identifier ? 'text-destructive' : ''}
                  >
                    模型标识符 *
                  </Label>
                  {matchedTemplate?.modelFetcher && (
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary" className="text-xs">
                        {matchedTemplate.display_name}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2"
                        onClick={() =>
                          editingModel?.api_provider &&
                          fetchModelsForProvider(editingModel.api_provider, true)
                        }
                        disabled={fetchingModels}
                      >
                        {fetchingModels ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <RefreshCw className="h-3 w-3" />
                        )}
                      </Button>
                    </div>
                  )}
                </div>

                {/* 模型标识符 Combobox */}
                {matchedTemplate?.modelFetcher ? (
                  <Popover open={modelComboboxOpen} onOpenChange={setModelComboboxOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        variant="outline"
                        role="combobox"
                        aria-expanded={modelComboboxOpen}
                        className="w-full justify-between font-normal"
                        disabled={fetchingModels || !!modelFetchError}
                      >
                        {fetchingModels ? (
                          <span className="flex items-center gap-2 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            正在获取模型列表...
                          </span>
                        ) : modelFetchError ? (
                          <span className="text-sm text-muted-foreground">
                            点击下方输入框手动填写
                          </span>
                        ) : editingModel?.model_identifier ? (
                          <span className="truncate">{editingModel.model_identifier}</span>
                        ) : (
                          <span className="text-muted-foreground">搜索或选择模型...</span>
                        )}
                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      className="p-0"
                      align="start"
                      style={{ width: 'var(--radix-popover-trigger-width)' }}
                    >
                      <Command>
                        <CommandInput placeholder="搜索模型..." />
                        <ScrollArea className="h-[300px]">
                          <CommandList className="max-h-none overflow-visible">
                            <CommandEmpty>
                              {modelFetchError ? (
                                <div className="space-y-2 px-2 py-4 text-center">
                                  <p className="text-destructive text-sm">{modelFetchError}</p>
                                  {!modelFetchError.includes('API Key') && (
                                    <Button
                                      variant="link"
                                      size="sm"
                                      onClick={() =>
                                        editingModel?.api_provider &&
                                        fetchModelsForProvider(editingModel.api_provider, true)
                                      }
                                    >
                                      重试
                                    </Button>
                                  )}
                                </div>
                              ) : (
                                '未找到匹配的模型'
                              )}
                            </CommandEmpty>
                            <CommandGroup heading="可用模型">
                              {availableModels.map((model) => (
                                <CommandItem
                                  key={model.id}
                                  value={model.id}
                                  onSelect={() => {
                                    setEditingModel((prev) =>
                                      prev ? { ...prev, model_identifier: model.id } : null
                                    )
                                    setModelComboboxOpen(false)
                                  }}
                                >
                                  <Check
                                    className={`mr-2 h-4 w-4 ${
                                      editingModel?.model_identifier === model.id
                                        ? 'opacity-100'
                                        : 'opacity-0'
                                    }`}
                                  />
                                  <div className="flex flex-col">
                                    <span>{model.id}</span>
                                    {model.name !== model.id && (
                                      <span className="text-xs text-muted-foreground">
                                        {model.name}
                                      </span>
                                    )}
                                  </div>
                                </CommandItem>
                              ))}
                            </CommandGroup>
                            <CommandGroup heading="手动输入">
                              <CommandItem
                                value="__manual_input__"
                                onSelect={() => {
                                  setModelComboboxOpen(false)
                                  // 聚焦到手动输入框（如果需要的话可以实现）
                                }}
                              >
                                <Pencil className="mr-2 h-4 w-4" />
                                手动输入模型标识符...
                              </CommandItem>
                            </CommandGroup>
                          </CommandList>
                        </ScrollArea>
                      </Command>
                    </PopoverContent>
                  </Popover>
                ) : (
                  <Input
                    id="model_identifier"
                    value={editingModel?.model_identifier || ''}
                    onChange={(e) => {
                      setEditingModel((prev) =>
                        prev ? { ...prev, model_identifier: e.target.value } : null
                      )
                      if (formErrors.model_identifier) {
                        setFormErrors((prev) => ({ ...prev, model_identifier: undefined }))
                      }
                    }}
                    placeholder="Qwen/Qwen3-30B-A3B-Instruct-2507"
                    className={
                      formErrors.model_identifier
                        ? 'border-destructive focus-visible:ring-destructive'
                        : ''
                    }
                  />
                )}

                {/* 表单验证错误提示 */}
                {formErrors.model_identifier && (
                  <p className="text-destructive text-xs">{formErrors.model_identifier}</p>
                )}

                {/* 模型获取错误提示 */}
                {modelFetchError &&
                  matchedTemplate?.modelFetcher &&
                  !formErrors.model_identifier && (
                    <Alert variant="destructive" className="mt-2 py-2">
                      <Info className="h-4 w-4" />
                      <AlertDescription className="text-xs">{modelFetchError}</AlertDescription>
                    </Alert>
                  )}

                {/* 手动输入区域 - 当使用 Combobox 时也显示一个可编辑的输入框 */}
                {matchedTemplate?.modelFetcher && (
                  <Input
                    value={editingModel?.model_identifier || ''}
                    onChange={(e) => {
                      setEditingModel((prev) =>
                        prev ? { ...prev, model_identifier: e.target.value } : null
                      )
                      if (formErrors.model_identifier) {
                        setFormErrors((prev) => ({ ...prev, model_identifier: undefined }))
                      }
                    }}
                    placeholder="或手动输入模型标识符"
                    className={`mt-2 ${formErrors.model_identifier ? 'border-destructive focus-visible:ring-destructive' : ''}`}
                  />
                )}

                {!formErrors.model_identifier && (
                  <p className="text-xs text-muted-foreground">
                    {modelFetchError
                      ? '请手动输入模型标识符，或前往"模型提供商配置"检查 API Key'
                      : matchedTemplate?.modelFetcher
                        ? `已识别为 ${matchedTemplate.display_name}，支持自动获取模型列表`
                        : 'API 提供商提供的模型 ID'}
                  </p>
                )}
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="price_in">输入价格 (¥/M token)</Label>
                  <Input
                    id="price_in"
                    type="number"
                    step="0.1"
                    min="0"
                    value={editingModel?.price_in ?? ''}
                    onChange={(e) => {
                      const val = e.target.value === '' ? null : parseFloat(e.target.value)
                      setEditingModel((prev) => (prev ? { ...prev, price_in: val } : null))
                    }}
                    placeholder="默认: 0"
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="price_out">输出价格 (¥/M token)</Label>
                  <Input
                    id="price_out"
                    type="number"
                    step="0.1"
                    min="0"
                    value={editingModel?.price_out ?? ''}
                    onChange={(e) => {
                      const val = e.target.value === '' ? null : parseFloat(e.target.value)
                      setEditingModel((prev) => (prev ? { ...prev, price_out: val } : null))
                    }}
                    placeholder="默认: 0"
                  />
                </div>
              </div>

              {/* 模型级别温度 */}
              <div className="space-y-3 rounded-[16px] border border-border/45 bg-muted/35 p-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="enable_model_temperature" className="cursor-pointer">
                      自定义模型温度
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      启用后将覆盖「为模型分配功能」中的任务温度配置
                    </p>
                  </div>
                  <Switch
                    id="enable_model_temperature"
                    checked={editingModel?.temperature != null}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        // 启用时设置默认值 0.5
                        setEditingModel((prev) => (prev ? { ...prev, temperature: 0.5 } : null))
                      } else {
                        // 禁用时清除温度
                        setEditingModel((prev) => (prev ? { ...prev, temperature: null } : null))
                      }
                    }}
                  />
                </div>

                {editingModel?.temperature != null && (
                  <div className="space-y-2 border-t pt-2">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm">温度值</Label>
                      <span className="text-sm font-medium tabular-nums">
                        {editingModel.temperature.toFixed(1)}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground">0</span>
                      <Slider
                        value={[editingModel.temperature]}
                        onValueChange={(values) =>
                          setEditingModel((prev) =>
                            prev ? { ...prev, temperature: values[0] } : null
                          )
                        }
                        min={0}
                        max={1}
                        step={0.1}
                        className="flex-1"
                      />
                      <span className="text-xs text-muted-foreground">1</span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      较低的温度（0.1-0.3）产生更确定的输出，较高的温度（0.7-1.0）产生更多样化的输出
                    </p>
                  </div>
                )}
              </div>

              {/* 模型级别最大 Token */}
              <div className="space-y-3 rounded-[16px] border border-border/45 bg-muted/35 p-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="enable_model_max_tokens" className="cursor-pointer">
                      自定义最大 Token
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      启用后将覆盖「为模型分配功能」中的任务最大 Token 配置
                    </p>
                  </div>
                  <Switch
                    id="enable_model_max_tokens"
                    checked={editingModel?.max_tokens != null}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        // 启用时设置默认值 2048
                        setEditingModel((prev) => (prev ? { ...prev, max_tokens: 2048 } : null))
                      } else {
                        // 禁用时清除
                        setEditingModel((prev) => (prev ? { ...prev, max_tokens: null } : null))
                      }
                    }}
                  />
                </div>

                {editingModel?.max_tokens != null && (
                  <div className="space-y-2 border-t pt-2">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm">最大 Token 数</Label>
                      <Input
                        type="number"
                        min="1"
                        max="128000"
                        value={editingModel.max_tokens}
                        onChange={(e) => {
                          const val = parseInt(e.target.value)
                          if (!isNaN(val) && val >= 1) {
                            setEditingModel((prev) => (prev ? { ...prev, max_tokens: val } : null))
                          }
                        }}
                        className="h-8 w-28 text-sm"
                      />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      限制模型单次输出的最大 token 数量，不同模型支持的上限不同
                    </p>
                  </div>
                )}
              </div>

              <div className="flex items-center space-x-2">
                <Switch
                  id="force_stream_mode"
                  checked={editingModel?.force_stream_mode || false}
                  onCheckedChange={(checked) =>
                    setEditingModel((prev) =>
                      prev ? { ...prev, force_stream_mode: checked } : null
                    )
                  }
                />
                <Label htmlFor="force_stream_mode" className="cursor-pointer">
                  强制流式输出模式
                </Label>
              </div>

              {/* 额外参数编辑器 */}
              <KeyValueEditor
                value={editingModel?.extra_params || {}}
                onChange={(params) =>
                  setEditingModel((prev) => (prev ? { ...prev, extra_params: params } : null))
                }
                placeholder="添加额外参数（如 enable_thinking、top_p 等）..."
              />
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              {editingIndex !== null && (
                <Button
                  variant="outline"
                  className="border-destructive/30 bg-destructive/5 text-destructive hover:bg-destructive/10 hover:text-destructive mr-auto"
                  onClick={() => {
                    const index = editingIndex
                    setEditDialogOpen(false)
                    setEditingModel(null)
                    setEditingIndex(null)
                    openDeleteDialog(index)
                  }}
                >
                  <Trash2 className="mr-2 h-4 w-4" strokeWidth={2} fill="none" />
                  删除模型
                </Button>
              )}
              <Button
                variant="outline"
                onClick={() => setEditDialogOpen(false)}
                data-tour="model-cancel-button"
              >
                取消
              </Button>
              <Button onClick={handleSaveEdit} data-tour="model-save-button">
                保存
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 删除确认对话框 */}
        <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认删除</AlertDialogTitle>
              <AlertDialogDescription>
                确定要删除模型 "{deletingIndex !== null ? models[deletingIndex]?.name : ''}" 吗？
                此操作无法撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction onClick={handleConfirmDelete}>删除</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* 批量删除确认对话框 */}
        <AlertDialog open={batchDeleteDialogOpen} onOpenChange={setBatchDeleteDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认批量删除</AlertDialogTitle>
              <AlertDialogDescription>
                确定要删除选中的 {selectedModels.size} 个模型吗？ 此操作无法撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                onClick={handleConfirmBatchDelete}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                批量删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* 重启遮罩层 */}
        {showRestartOverlay && (
          <RestartingOverlay
            onRestartComplete={handleRestartComplete}
            onRestartFailed={handleRestartFailed}
          />
        )}
      </div>
    </ScrollArea>
  )
}
