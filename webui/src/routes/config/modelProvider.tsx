import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'

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
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Plus,
  Pencil,
  Trash2,
  Save,
  Eye,
  EyeOff,
  Copy,
  Search,
  Power,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Check,
  ChevronsUpDown,
  Zap,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Server,
} from 'lucide-react'
import {
  getModelConfig,
  updateModelConfig,
  updateModelConfigSection,
  testProviderConnection,
  type TestConnectionResult,
} from '@/lib/config-api'
import { restartRiyaBot } from '@/lib/system-api'
import { useToast } from '@/hooks/use-toast'
import { useTour } from '@/components/tour'
import {
  MODEL_ASSIGNMENT_TOUR_ID,
  modelAssignmentTourSteps,
  STEP_ROUTE_MAP,
} from '@/components/tour/tours/model-assignment-tour'
import { useNavigate } from '@tanstack/react-router'
import { RestartingOverlay } from '@/components/RestartingOverlay'
import { PROVIDER_TEMPLATES } from './providerTemplates'

interface APIProvider {
  name: string
  base_url: string
  api_key: string
  client_type: string
  max_retry: number | null
  timeout: number | null
  retry_interval: number | null
}

export function ModelProviderConfigPage() {
  const [providers, setProviders] = useState<APIProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [autoSaving, setAutoSaving] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [showRestartOverlay, setShowRestartOverlay] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<APIProvider | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState<string>('custom')
  const [templateComboboxOpen, setTemplateComboboxOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null)
  const [showApiKey, setShowApiKey] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedProviders, setSelectedProviders] = useState<Set<number>>(new Set())
  const [batchDeleteDialogOpen, setBatchDeleteDialogOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [jumpToPage, setJumpToPage] = useState('')

  // 表单验证错误状态
  const [formErrors, setFormErrors] = useState<{
    name?: string
    base_url?: string
    api_key?: string
  }>({})

  // 测试连接状态
  const [testingProviders, setTestingProviders] = useState<Set<string>>(new Set())
  const [testResults, setTestResults] = useState<Map<string, TestConnectionResult>>(new Map())

  const { toast } = useToast()
  const navigate = useNavigate()
  const { state: tourState, goToStep, registerTour } = useTour()

  // 用于防抖的定时器
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const initialLoadRef = useRef(true)

  // 注册 Tour（确保跨页导航时 Tour 仍然可用）
  useEffect(() => {
    registerTour(MODEL_ASSIGNMENT_TOUR_ID, modelAssignmentTourSteps)
  }, [registerTour])

  // 监听 Tour 步骤变化，处理页面导航
  useEffect(() => {
    if (tourState.activeTourId === MODEL_ASSIGNMENT_TOUR_ID && tourState.isRunning) {
      const targetRoute = STEP_ROUTE_MAP[tourState.stepIndex]
      if (targetRoute && !window.location.pathname.endsWith(targetRoute.replace('/config/', ''))) {
        navigate({ to: targetRoute })
      }
    }
  }, [tourState.stepIndex, tourState.activeTourId, tourState.isRunning, navigate])

  // 监听 Tour 步骤变化，处理弹窗的打开和关闭
  // 提供商弹窗步骤: 3-9 (index 3-9)，弹窗外步骤: 0-2 (index 0-2) 和 10+ (index 10+)
  const prevTourStepRef = useRef(tourState.stepIndex)
  useEffect(() => {
    if (tourState.activeTourId === MODEL_ASSIGNMENT_TOUR_ID && tourState.isRunning) {
      const prevStep = prevTourStepRef.current
      const currentStep = tourState.stepIndex

      // 如果从弹窗内步骤 (3-9) 回退到弹窗外步骤 (0-2)，关闭弹窗
      if (prevStep >= 3 && prevStep <= 9 && currentStep < 3) {
        setEditDialogOpen(false)
      }

      // 如果从弹窗外步骤 (10+) 回退到弹窗内步骤 (3-9)，重新打开弹窗
      // 这处理了从模型管理页面第 11 步点击"上一步"回到提供商弹窗的情况
      if (prevStep >= 10 && currentStep >= 3 && currentStep <= 9) {
        // 需要打开空白弹窗以便 Tour 可以定位到弹窗内的元素
        setFormErrors({})
        setSelectedTemplate('custom')
        setEditingProvider({
          name: '',
          base_url: '',
          api_key: '',
          client_type: 'openai',
          max_retry: 2,
          timeout: 30,
          retry_interval: 10,
        })
        setEditingIndex(null)
        setShowApiKey(false)
        setEditDialogOpen(true)
      }

      prevTourStepRef.current = currentStep
    }
  }, [tourState.stepIndex, tourState.activeTourId, tourState.isRunning])

  // 处理 Tour 中需要用户点击才能继续的步骤
  useEffect(() => {
    if (tourState.activeTourId !== MODEL_ASSIGNMENT_TOUR_ID || !tourState.isRunning) return

    const handleTourClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      const currentStep = tourState.stepIndex

      // Step 3 (index 2): 点击添加提供商按钮
      if (currentStep === 2 && target.closest('[data-tour="add-provider-button"]')) {
        setTimeout(() => goToStep(3), 300)
      }
      // Step 10 (index 9): 点击取消按钮（关闭提供商弹窗）
      else if (currentStep === 9 && target.closest('[data-tour="provider-cancel-button"]')) {
        setTimeout(() => goToStep(10), 300)
      }
    }

    document.addEventListener('click', handleTourClick, true)
    return () => document.removeEventListener('click', handleTourClick, true)
  }, [tourState, goToStep])

  // 加载配置
  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    try {
      setLoading(true)
      const config = await getModelConfig()
      setProviders((config.api_providers as APIProvider[]) || [])
      setHasUnsavedChanges(false)
      initialLoadRef.current = false
    } catch (error) {
      console.error('加载配置失败:', error)
    } finally {
      setLoading(false)
    }
  }

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

  // 保存并重启
  const handleSaveAndRestart = async () => {
    try {
      setSaving(true)
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current)
      }
      const config = await getModelConfig()
      config.api_providers = providers
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

  // 自动保存函数（使用增量 API）
  const autoSaveProviders = useCallback(async (newProviders: APIProvider[]) => {
    if (initialLoadRef.current) return // 初始加载时不自动保存

    try {
      setAutoSaving(true)
      await updateModelConfigSection('api_providers', newProviders)
      setHasUnsavedChanges(false)
    } catch (error) {
      console.error('自动保存失败:', error)
      // 自动保存失败时不显示错误提示，避免打扰用户
      setHasUnsavedChanges(true)
    } finally {
      setAutoSaving(false)
    }
  }, [])

  // 监听 providers 变化，触发自动保存（带防抖）
  useEffect(() => {
    if (initialLoadRef.current) return

    setHasUnsavedChanges(true)

    // 清除之前的定时器
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current)
    }

    // 设置新的定时器（2秒后自动保存）
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveProviders(providers)
    }, 2000)

    // 清理函数
    return () => {
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current)
      }
    }
  }, [providers, autoSaveProviders])

  // 保存配置（手动保存，保存完整配置）
  const saveConfig = async () => {
    try {
      setSaving(true)

      // 先取消自动保存定时器
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current)
      }

      const config = await getModelConfig()
      config.api_providers = providers
      await updateModelConfig(config)
      setHasUnsavedChanges(false)
      toast({
        title: '保存成功',
        description: '模型提供商配置已保存',
      })
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
  const openEditDialog = (provider: APIProvider | null, index: number | null) => {
    // 清除表单验证错误
    setFormErrors({})

    if (provider) {
      // 编辑现有提供商 - 检测匹配的模板
      const matchedTemplate = PROVIDER_TEMPLATES.find(
        (t) => t.base_url === provider.base_url && t.client_type === provider.client_type
      )
      setSelectedTemplate(matchedTemplate?.id || 'custom')
      setEditingProvider(provider)
    } else {
      // 新建提供商 - 默认使用自定义模板
      setSelectedTemplate('custom')
      setEditingProvider({
        name: '',
        base_url: '',
        api_key: '',
        client_type: 'openai',
        max_retry: 2,
        timeout: 30,
        retry_interval: 10,
      })
    }
    setEditingIndex(index)
    setShowApiKey(false)
    setEditDialogOpen(true)
  }

  // 处理模板选择变化
  const handleTemplateChange = (templateId: string) => {
    setSelectedTemplate(templateId)
    setTemplateComboboxOpen(false)
    const template = PROVIDER_TEMPLATES.find((t) => t.id === templateId)
    if (template && template.id !== 'custom') {
      // 应用模板配置
      setEditingProvider((prev) => ({
        ...prev!,
        name: template.name,
        base_url: template.base_url,
        client_type: template.client_type,
      }))
    } else if (template?.id === 'custom') {
      // 切换到自定义模板 - 清空URL和客户端类型(保留其他字段)
      setEditingProvider((prev) => ({
        ...prev!,
        name: '',
        base_url: '',
        client_type: 'openai',
      }))
    }
  }

  // 判断当前是否使用模板(非自定义)
  const isUsingTemplate = useMemo(() => {
    return selectedTemplate !== 'custom'
  }, [selectedTemplate])

  // 复制 API Key
  const copyApiKey = async () => {
    if (!editingProvider?.api_key) return
    try {
      await navigator.clipboard.writeText(editingProvider.api_key)
      toast({
        title: '复制成功',
        description: 'API Key 已复制到剪贴板',
      })
    } catch {
      toast({
        title: '复制失败',
        description: '无法访问剪贴板',
        variant: 'destructive',
      })
    }
  }

  // 保存编辑
  const handleSaveEdit = () => {
    if (!editingProvider) return

    // 验证必填项
    const errors: { name?: string; base_url?: string; api_key?: string } = {}
    if (!editingProvider.name?.trim()) {
      errors.name = '请输入提供商名称'
    }
    if (!editingProvider.base_url?.trim()) {
      errors.base_url = '请输入基础 URL'
    }
    if (!editingProvider.api_key?.trim()) {
      errors.api_key = '请输入 API Key'
    }

    if (Object.keys(errors).length > 0) {
      setFormErrors(errors)
      return
    }

    // 清除错误状态
    setFormErrors({})

    // 填充空值的默认值
    const providerToSave = {
      ...editingProvider,
      max_retry: editingProvider.max_retry ?? 2,
      timeout: editingProvider.timeout ?? 30,
      retry_interval: editingProvider.retry_interval ?? 10,
    }

    if (editingIndex !== null) {
      // 更新现有提供商
      const newProviders = [...providers]
      newProviders[editingIndex] = providerToSave
      setProviders(newProviders)
    } else {
      // 添加新提供商
      setProviders([...providers, providerToSave])
    }

    setEditDialogOpen(false)
    setEditingProvider(null)
    setEditingIndex(null)
  }

  // 处理编辑对话框关闭
  const handleEditDialogClose = (open: boolean) => {
    if (!open && editingProvider) {
      // 关闭时填充默认值
      const updatedProvider = {
        ...editingProvider,
        max_retry: editingProvider.max_retry ?? 2,
        timeout: editingProvider.timeout ?? 30,
        retry_interval: editingProvider.retry_interval ?? 10,
      }
      setEditingProvider(updatedProvider)
    }
    setEditDialogOpen(open)
  }

  // 打开删除确认对话框
  const openDeleteDialog = (index: number) => {
    setDeletingIndex(index)
    setDeleteDialogOpen(true)
  }

  // 确认删除提供商
  const handleConfirmDelete = () => {
    if (deletingIndex !== null) {
      const newProviders = providers.filter((_, i) => i !== deletingIndex)
      setProviders(newProviders)
      toast({
        title: '删除成功',
        description: '提供商已从列表中移除',
      })
    }
    setDeleteDialogOpen(false)
    setDeletingIndex(null)
  }

  // 切换单个提供商选择
  const toggleProviderSelection = (index: number) => {
    const newSelected = new Set(selectedProviders)
    if (newSelected.has(index)) {
      newSelected.delete(index)
    } else {
      newSelected.add(index)
    }
    setSelectedProviders(newSelected)
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedProviders.size === filteredProviders.length) {
      setSelectedProviders(new Set())
    } else {
      const allIndices = filteredProviders.map((_, idx) =>
        providers.findIndex((p) => p === filteredProviders[idx])
      )
      setSelectedProviders(new Set(allIndices))
    }
  }

  // 打开批量删除确认对话框
  const openBatchDeleteDialog = () => {
    if (selectedProviders.size === 0) {
      toast({
        title: '提示',
        description: '请先选择要删除的提供商',
        variant: 'default',
      })
      return
    }
    setBatchDeleteDialogOpen(true)
  }

  // 确认批量删除
  const handleConfirmBatchDelete = () => {
    const newProviders = providers.filter((_, index) => !selectedProviders.has(index))
    setProviders(newProviders)
    setSelectedProviders(new Set())
    setBatchDeleteDialogOpen(false)
    toast({
      title: '批量删除成功',
      description: `已删除 ${selectedProviders.size} 个提供商`,
    })
  }

  // 过滤提供商列表
  const filteredProviders = providers.filter((provider) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      provider.name.toLowerCase().includes(query) ||
      provider.base_url.toLowerCase().includes(query) ||
      provider.client_type.toLowerCase().includes(query)
    )
  })

  // 分页逻辑
  const totalPages = Math.ceil(filteredProviders.length / pageSize)
  const paginatedProviders = filteredProviders.slice((page - 1) * pageSize, page * pageSize)

  // 页码跳转
  const handleJumpToPage = () => {
    const targetPage = parseInt(jumpToPage)
    if (targetPage >= 1 && targetPage <= totalPages) {
      setPage(targetPage)
      setJumpToPage('')
    }
  }

  // 测试单个提供商连接
  const handleTestConnection = async (providerName: string) => {
    // 标记正在测试
    setTestingProviders((prev) => new Set(prev).add(providerName))

    try {
      const result = await testProviderConnection(providerName)
      setTestResults((prev) => new Map(prev).set(providerName, result))

      // 显示结果 toast
      if (result.network_ok) {
        if (result.api_key_valid === true) {
          toast({
            title: '连接正常',
            description: `${providerName} 网络连接正常，API Key 有效 (${result.latency_ms}ms)`,
          })
        } else if (result.api_key_valid === false) {
          toast({
            title: '连接正常但 Key 无效',
            description: `${providerName} 网络连接正常，但 API Key 无效或已过期`,
            variant: 'destructive',
          })
        } else {
          toast({
            title: '网络连接正常',
            description: `${providerName} 可以访问 (${result.latency_ms}ms)`,
          })
        }
      } else {
        toast({
          title: '连接失败',
          description: result.error || '无法连接到提供商',
          variant: 'destructive',
        })
      }
    } catch (error) {
      toast({
        title: '测试失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
    } finally {
      setTestingProviders((prev) => {
        const newSet = new Set(prev)
        newSet.delete(providerName)
        return newSet
      })
    }
  }

  // 批量测试所有提供商
  const handleTestAllConnections = async () => {
    for (const provider of providers) {
      await handleTestConnection(provider.name)
    }
  }

  // 渲染测试状态指示器
  const renderTestStatus = (providerName: string) => {
    const isTesting = testingProviders.has(providerName)
    const result = testResults.get(providerName)

    if (isTesting) {
      return (
        <Badge
          variant="secondary"
          className="gap-1 border-0 bg-secondary/80 text-muted-foreground shadow-none"
        >
          <Loader2 className="h-3 w-3 animate-spin" />
          测试中
        </Badge>
      )
    }

    if (!result) return null

    if (result.network_ok) {
      if (result.api_key_valid === true) {
        return (
          <Badge className="gap-1 border-0 bg-[rgb(52_199_89_/_0.11)] text-[rgb(36_138_61)] shadow-none hover:bg-[rgb(52_199_89_/_0.15)] dark:text-[rgb(48_209_88)]">
            <CheckCircle2 className="h-3 w-3" />
            正常
          </Badge>
        )
      } else if (result.api_key_valid === false) {
        return (
          <Badge
            variant="destructive"
            className="gap-1 border-0 bg-[rgb(255_59_48_/_0.11)] text-[rgb(174_37_31)] shadow-none hover:bg-[rgb(255_59_48_/_0.15)] dark:text-[rgb(255_105_97)]"
          >
            <AlertCircle className="h-3 w-3" />
            Key无效
          </Badge>
        )
      } else {
        return (
          <Badge className="gap-1 border-0 bg-[rgb(0_122_255_/_0.11)] text-[rgb(0_102_204)] shadow-none hover:bg-[rgb(0_122_255_/_0.15)] dark:text-[rgb(100_210_255)]">
            <CheckCircle2 className="h-3 w-3" />
            可访问
          </Badge>
        )
      }
    } else {
      return (
        <Badge
          variant="destructive"
          className="gap-1 border-0 bg-[rgb(255_59_48_/_0.11)] text-[rgb(174_37_31)] shadow-none hover:bg-[rgb(255_59_48_/_0.15)] dark:text-[rgb(255_105_97)]"
        >
          <XCircle className="h-3 w-3" />
          离线
        </Badge>
      )
    }
  }

  if (loading) {
    return (
      <div className="ios-page">
        <div className="ios-content">
          <div className="space-y-2 px-1">
            <Skeleton className="h-9 w-64 rounded-[12px]" />
            <Skeleton className="h-5 w-52 rounded-[10px]" />
          </div>
          <div className="ios-group overflow-hidden p-4 sm:p-5">
            <div className="flex items-center justify-between gap-4">
              <div className="space-y-2">
                <Skeleton className="h-5 w-32 rounded-[10px]" />
                <Skeleton className="h-4 w-48 rounded-[9px]" />
              </div>
              <Skeleton className="h-9 w-28 rounded-full" />
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
    )
  }

  const saveLabel = saving
    ? '保存中...'
    : autoSaving
      ? '自动保存中...'
      : hasUnsavedChanges
        ? '保存配置'
        : '已保存'
  const saveDescription = hasUnsavedChanges ? '有更改等待写入配置' : '当前配置已写入'
  const renderProviderMeta = (provider: APIProvider) => (
    <span className="mt-1.5 flex flex-wrap gap-1.5">
      {[provider.client_type, `重试 ${provider.max_retry}`, `超时 ${provider.timeout}s`].map(
        (item) => (
          <span
            key={item}
            className="rounded-full bg-secondary/70 px-2 py-0.5 text-[11.5px] font-medium leading-4 text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.5)_inset]"
          >
            {item}
          </span>
        )
      )}
    </span>
  )

  return (
    <div className="ios-page space-y-6 sm:space-y-8">
      {/* 页面标题 */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="ios-title">AI 模型厂商配置</h1>
          <p className="ios-subtitle">管理 AI 模型厂商的 API 配置</p>
        </div>
        <div className="hidden w-full grid-cols-[2.75rem_minmax(0,1fr)_2.75rem_2.75rem] gap-2 sm:flex sm:w-auto sm:flex-row">
          {selectedProviders.size > 0 && (
            <Button
              onClick={openBatchDeleteDialog}
              size="sm"
              variant="destructive"
              className="col-span-4 h-11 w-full sm:w-auto"
            >
              <Trash2 className="mr-2 h-4 w-4" strokeWidth={2} fill="none" />
              批量删除 ({selectedProviders.size})
            </Button>
          )}
          <Button
            onClick={handleTestAllConnections}
            size="sm"
            variant="outline"
            className="h-11 w-11 px-0 sm:w-auto sm:px-4"
            disabled={providers.length === 0 || testingProviders.size > 0}
            aria-label={
              testingProviders.size > 0
                ? `测试中，剩余 ${testingProviders.size} 个`
                : '测试全部提供商'
            }
            title={testingProviders.size > 0 ? `测试中 (${testingProviders.size})` : '测试全部'}
          >
            <Zap className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">
              {testingProviders.size > 0 ? `测试中 (${testingProviders.size})` : '测试全部'}
            </span>
          </Button>
          <Button
            onClick={() => openEditDialog(null, null)}
            size="sm"
            className="h-11 min-w-0 px-4 sm:w-auto"
            data-tour="add-provider-button"
          >
            <Plus className="mr-2 h-4 w-4" strokeWidth={2} fill="none" />
            <span className="truncate">添加提供商</span>
          </Button>
          <Button
            onClick={saveConfig}
            disabled={saving || autoSaving || !hasUnsavedChanges || restarting}
            size="sm"
            variant="outline"
            className="h-11 w-11 px-0 sm:w-auto sm:min-w-[120px] sm:px-4"
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
                className="h-11 w-11 px-0 sm:w-auto sm:min-w-[120px] sm:px-4"
                aria-label={restarting ? '重启中' : hasUnsavedChanges ? '保存并重启' : '重启主程序'}
                title={restarting ? '重启中...' : hasUnsavedChanges ? '保存并重启' : '重启主程序'}
              >
                <Power className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">
                  {restarting ? '重启中...' : hasUnsavedChanges ? '保存并重启' : '重启主程序'}
                </span>
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
          onClick={() => openEditDialog(null, null)}
          className="ios-row ios-touch min-h-[54px] w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
          data-tour="add-provider-button"
        >
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
              <Plus className="h-4 w-4" strokeWidth={2} fill="none" />
            </span>
            <span className="text-[15px] font-medium leading-5">添加提供商</span>
          </span>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
        </button>
        <button
          type="button"
          onClick={handleTestAllConnections}
          disabled={providers.length === 0 || testingProviders.size > 0}
          className="ios-row ios-touch min-h-[54px] w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-60"
        >
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
              {testingProviders.size > 0 ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Zap className="h-4 w-4" />
              )}
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-medium leading-5">
                {testingProviders.size > 0 ? `测试中 (${testingProviders.size})` : '测试全部'}
              </span>
              <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                检查所有提供商连接状态
              </span>
            </span>
          </span>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
        </button>
        <div
          className="ios-row min-h-[58px] w-full text-left"
        >
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-teal">
              <Save className="h-4 w-4" strokeWidth={2} fill="none" />
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-medium leading-5">{saveLabel}</span>
              <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                {saveDescription}
              </span>
            </span>
          </span>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button
                type="button"
                disabled={saving || autoSaving || restarting}
                className="ios-touch ml-3 inline-flex h-11 min-w-[4.75rem] shrink-0 items-center justify-center rounded-full bg-[rgb(120_120_128_/_0.12)] px-4 text-[14px] font-semibold leading-5 text-foreground/82 shadow-[inset_0_0_0_1px_rgba(60,60,67,0.08)] hover:bg-[rgb(120_120_128_/_0.16)] active:bg-[rgb(120_120_128_/_0.2)] disabled:opacity-60 dark:bg-white/[0.12] dark:shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)] dark:hover:bg-white/[0.16]"
              >
                {hasUnsavedChanges ? '保存并重启' : '重启'}
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
        </div>
        {selectedProviders.size > 0 && (
          <button
            type="button"
            onClick={openBatchDeleteDialog}
            className="ios-row ios-touch text-destructive w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-red">
                <Trash2 className="h-4 w-4" strokeWidth={2} fill="none" />
              </span>
              <span className="text-[15px] font-medium leading-5">
                批量删除 ({selectedProviders.size})
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
          </button>
        )}
      </div>
      <ScrollArea className="ios-scrollbar-none h-[calc(100vh-252px)]">
        <div className="space-y-5 pr-1">
          {/* 搜索框 */}
          <div className="ios-group overflow-hidden px-4 py-3 sm:hidden">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="搜索提供商"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-11 rounded-[12px] border-0 bg-muted pl-10 text-[16px] shadow-none focus-visible:ring-0"
              />
            </div>
          </div>
          <div className="hidden items-center gap-3 sm:flex">
            <div className="relative w-full sm:max-w-sm sm:flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="搜索提供商名称、URL 或类型..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-11 rounded-[12px] border-0 bg-muted/75 pl-9 shadow-none focus-visible:ring-0"
              />
            </div>
            {searchQuery && (
              <p className="whitespace-nowrap text-sm text-muted-foreground">
                找到 {filteredProviders.length} 个结果
              </p>
            )}
          </div>

          {/* 提供商列表 - 移动端卡片视图 */}
          <div className="ios-group overflow-hidden md:hidden">
            {filteredProviders.length === 0 ? (
              <div className="ios-empty-state">
                <span className="ios-empty-illustration">
                  <Server className="h-7 w-7 text-primary" />
                </span>
                <span className="space-y-1.5">
                  <span className="block text-[15px] font-semibold leading-5 text-foreground">
                    {searchQuery ? '未找到匹配的提供商' : '暂无提供商配置'}
                  </span>
                  <span className="block text-[13px] leading-5 text-muted-foreground">
                    {searchQuery ? '换个关键词再试试' : '添加提供商后会显示在这里'}
                  </span>
                </span>
              </div>
            ) : (
              paginatedProviders.map((provider, displayIndex) => {
                const actualIndex = providers.findIndex((p) => p === provider)

                return (
                  <div
                    key={displayIndex}
                    className="relative grid min-h-[98px] grid-cols-[minmax(0,1fr)_112px] items-center after:absolute after:bottom-0 after:left-16 after:right-0 after:h-px after:bg-border/55 last:after:hidden"
                  >
                    <button
                      type="button"
                      onClick={() => openEditDialog(provider, actualIndex)}
                      className="ios-touch grid min-h-[98px] w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 pr-1 text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                    >
                      <span className="ios-symbol ios-symbol-md ios-symbol-purple">
                        <Server className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="truncate text-[16px] font-semibold leading-6">
                            {provider.name}
                          </span>
                          {renderTestStatus(provider.name)}
                        </span>
                        <span
                          className="block truncate text-[13px] leading-5 text-muted-foreground"
                          title={provider.base_url}
                        >
                          {provider.base_url}
                        </span>
                        {renderProviderMeta(provider)}
                      </span>
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
                    </button>
                    <span className="mr-2 flex shrink-0 items-center justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => handleTestConnection(provider.name)}
                        disabled={testingProviders.has(provider.name)}
                        className="ios-touch grid h-11 w-12 place-items-center rounded-full text-foreground hover:bg-accent/70 focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-60"
                        aria-label={`测试提供商 ${provider.name}`}
                        title="测试连接"
                      >
                        {testingProviders.has(provider.name) ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Zap className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => openDeleteDialog(actualIndex)}
                        className="ios-touch grid h-11 w-12 place-items-center rounded-full text-[rgb(215_0_21)] hover:bg-[rgb(255_59_48_/_0.08)] hover:text-[rgb(174_37_31)] focus-visible:bg-[rgb(255_59_48_/_0.08)] focus-visible:text-[rgb(174_37_31)] focus-visible:ring-0 dark:text-[rgb(255_105_97)] dark:hover:bg-[rgb(255_69_58_/_0.12)]"
                        aria-label={`删除提供商 ${provider.name}`}
                        title="删除"
                      >
                        <Trash2 className="h-4 w-4" strokeWidth={2} fill="none" />
                      </button>
                    </span>
                  </div>
                )
              })
            )}
          </div>

          {/* 提供商列表 - 桌面端分组列表视图 */}
          <div className="ios-group hidden overflow-hidden md:block">
            {filteredProviders.length > 0 && (
              <div className="flex min-h-12 items-center justify-between gap-4 border-b border-border/45 px-5 text-[13px] leading-5 text-muted-foreground">
                <label className="ios-touch flex items-center gap-2 rounded-full pr-2">
                  <span className="sr-only">选择全部提供商</span>
                  <Checkbox
                    checked={
                      selectedProviders.size === filteredProviders.length &&
                      filteredProviders.length > 0
                    }
                    onCheckedChange={toggleSelectAll}
                    aria-label="选择全部提供商"
                  />
                  <span>选择全部</span>
                </label>
                <span>{filteredProviders.length} 个提供商</span>
              </div>
            )}
            {paginatedProviders.length === 0 ? (
              <div className="ios-empty-state">
                <span className="ios-empty-illustration">
                  <Server className="h-7 w-7 text-primary" />
                </span>
                <span className="space-y-1.5">
                  <span className="block text-[15px] font-semibold leading-5 text-foreground">
                    {searchQuery ? '未找到匹配的提供商' : '暂无提供商配置'}
                  </span>
                  <span className="block text-[13px] leading-5 text-muted-foreground">
                    {searchQuery ? '换个关键词再试试' : '添加提供商后会显示在这里'}
                  </span>
                </span>
              </div>
            ) : (
              paginatedProviders.map((provider, displayIndex) => {
                const actualIndex = providers.findIndex((p) => p === provider)
                return (
                  <div
                    key={displayIndex}
                    className="ios-touch flex min-h-[84px] items-center gap-4 border-b border-border/45 px-5 py-3 last:border-b-0 hover:bg-[rgb(120_120_128_/_0.06)]"
                  >
                    <div className="w-11 shrink-0">
                      <Checkbox
                        checked={selectedProviders.has(actualIndex)}
                        onCheckedChange={() => toggleProviderSelection(actualIndex)}
                        aria-label={`选择提供商 ${provider.name}`}
                      />
                    </div>
                    <span className="ios-symbol ios-symbol-md ios-symbol-purple">
                      <Server className="h-4 w-4" />
                    </span>
                    <button
                      type="button"
                      onClick={() => openEditDialog(provider, actualIndex)}
                      className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35"
                    >
                      <span className="block truncate text-[15px] font-semibold leading-6 text-foreground">
                        {provider.name}
                      </span>
                      <span
                        className="mt-0.5 block truncate text-[13px] leading-5 text-muted-foreground"
                        title={provider.base_url}
                      >
                        {provider.base_url}
                      </span>
                      {renderProviderMeta(provider)}
                    </button>
                    <div className="flex w-28 shrink-0 justify-end lg:w-32">
                      {renderTestStatus(provider.name) || (
                        <Badge
                          variant="secondary"
                          className="border-0 bg-secondary/80 text-muted-foreground shadow-none"
                        >
                          未测试
                        </Badge>
                      )}
                    </div>
                    <div className="flex w-40 shrink-0 justify-end gap-2">
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => handleTestConnection(provider.name)}
                        disabled={testingProviders.has(provider.name)}
                        className="h-11 w-11 rounded-full"
                        aria-label={`测试提供商 ${provider.name}`}
                        title="测试连接"
                      >
                        {testingProviders.has(provider.name) ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Zap className="h-4 w-4" />
                        )}
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => openEditDialog(provider, actualIndex)}
                        className="h-11 w-11 rounded-full"
                        aria-label={`编辑提供商 ${provider.name}`}
                        title="编辑"
                      >
                        <Pencil className="h-4 w-4" strokeWidth={2} fill="none" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openDeleteDialog(actualIndex)}
                        className="h-11 w-11 rounded-full text-[rgb(215_0_21)] hover:bg-[rgb(255_59_48_/_0.08)] hover:text-[rgb(174_37_31)] dark:text-[rgb(255_105_97)] dark:hover:bg-[rgb(255_69_58_/_0.12)]"
                        aria-label={`删除提供商 ${provider.name}`}
                        title="删除"
                      >
                        <Trash2 className="h-4 w-4" strokeWidth={2} fill="none" />
                      </Button>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {/* 分页 - 增强版 */}
          {filteredProviders.length > 0 && (
            <>
              <div className="mt-4 md:hidden">
                <div className="ios-group flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <p className="text-[15px] font-medium">
                      第 {page} / {totalPages} 页
                    </p>
                    <p className="mt-1 truncate text-[13px] text-muted-foreground">
                      显示 {(page - 1) * pageSize + 1} 到{' '}
                      {Math.min(page * pageSize, filteredProviders.length)} 条，共{' '}
                      {filteredProviders.length} 条
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="h-11 w-11 rounded-full"
                      aria-label="上一页"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setPage((p) => p + 1)}
                      disabled={page >= totalPages}
                      className="h-11 w-11 rounded-full"
                      aria-label="下一页"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </div>
              <div className="ios-group hidden items-center justify-between gap-4 px-5 py-3 md:flex">
                <div className="flex items-center gap-2">
                  <Label htmlFor="page-size-provider" className="whitespace-nowrap text-sm">
                    每页显示
                  </Label>
                  <Select
                    value={pageSize.toString()}
                    onValueChange={(value) => {
                      setPageSize(parseInt(value))
                      setPage(1)
                      setSelectedProviders(new Set())
                    }}
                  >
                    <SelectTrigger id="page-size-provider" className="w-20">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="10">10</SelectItem>
                      <SelectItem value="20">20</SelectItem>
                      <SelectItem value="50">50</SelectItem>
                      <SelectItem value="100">100</SelectItem>
                    </SelectContent>
                  </Select>
                  <span className="text-sm text-muted-foreground">
                    显示 {(page - 1) * pageSize + 1} 到{' '}
                    {Math.min(page * pageSize, filteredProviders.length)} 条，共{' '}
                    {filteredProviders.length} 条
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(1)}
                    disabled={page === 1}
                    className="hidden sm:flex"
                  >
                    <ChevronsLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
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
                      className="h-11 w-20 text-center"
                      min={1}
                      max={totalPages}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleJumpToPage}
                      disabled={!jumpToPage}
                      className="h-11"
                    >
                      跳转
                    </Button>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={page >= totalPages}
                  >
                    <span className="hidden sm:inline">下一页</span>
                    <ChevronRight className="h-4 w-4 sm:ml-1" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(totalPages)}
                    disabled={page >= totalPages}
                    className="hidden sm:flex"
                  >
                    <ChevronsRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </ScrollArea>

      {/* 编辑对话框 */}
      <Dialog open={editDialogOpen} onOpenChange={handleEditDialogClose}>
        <DialogContent
          className="max-h-[90vh] max-w-[95vw] overflow-y-auto sm:max-w-2xl"
          data-tour="provider-dialog"
          preventOutsideClose={tourState.isRunning}
        >
          <DialogHeader>
            <DialogTitle>{editingIndex !== null ? '编辑提供商' : '添加提供商'}</DialogTitle>
            <DialogDescription>配置 API 提供商的连接信息和参数</DialogDescription>
          </DialogHeader>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              handleSaveEdit()
            }}
            autoComplete="off"
          >
            <div className="grid gap-4 py-4">
              <div className="grid gap-2" data-tour="provider-template-select">
                <Label htmlFor="template">提供商模板</Label>
                <Popover open={templateComboboxOpen} onOpenChange={setTemplateComboboxOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      role="combobox"
                      aria-expanded={templateComboboxOpen}
                      className="w-full justify-between"
                    >
                      {selectedTemplate
                        ? PROVIDER_TEMPLATES.find((template) => template.id === selectedTemplate)
                            ?.display_name
                        : '选择提供商模板...'}
                      <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent
                    className="p-0"
                    align="start"
                    style={{ width: 'var(--radix-popover-trigger-width)' }}
                  >
                    <Command>
                      <CommandInput placeholder="搜索提供商模板..." />
                      <ScrollArea className="h-[300px]">
                        <CommandList className="max-h-none overflow-visible">
                          <CommandEmpty>未找到匹配的模板</CommandEmpty>
                          <CommandGroup>
                            {PROVIDER_TEMPLATES.map((template) => (
                              <CommandItem
                                key={template.id}
                                value={template.display_name}
                                onSelect={() => handleTemplateChange(template.id)}
                              >
                                <Check
                                  className={`mr-2 h-4 w-4 ${
                                    selectedTemplate === template.id ? 'opacity-100' : 'opacity-0'
                                  }`}
                                />
                                {template.display_name}
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </ScrollArea>
                    </Command>
                  </PopoverContent>
                </Popover>
                <p className="text-xs text-muted-foreground">
                  选择预设模板可自动填充 URL 和客户端类型,支持搜索
                </p>
              </div>

              <div className="grid gap-2" data-tour="provider-name-input">
                <Label htmlFor="name" className={formErrors.name ? 'text-destructive' : ''}>
                  名称 *
                </Label>
                <Input
                  id="name"
                  value={editingProvider?.name || ''}
                  onChange={(e) => {
                    setEditingProvider((prev) => (prev ? { ...prev, name: e.target.value } : null))
                    if (formErrors.name) {
                      setFormErrors((prev) => ({ ...prev, name: undefined }))
                    }
                  }}
                  placeholder="例如: DeepSeek, SiliconFlow"
                  className={
                    formErrors.name ? 'border-destructive focus-visible:ring-destructive' : ''
                  }
                />
                {formErrors.name && <p className="text-destructive text-xs">{formErrors.name}</p>}
              </div>

              <div className="grid gap-2" data-tour="provider-url-input">
                <Label htmlFor="base_url" className={formErrors.base_url ? 'text-destructive' : ''}>
                  基础 URL *
                </Label>
                <Input
                  id="base_url"
                  value={editingProvider?.base_url || ''}
                  onChange={(e) => {
                    setEditingProvider((prev) =>
                      prev ? { ...prev, base_url: e.target.value } : null
                    )
                    if (formErrors.base_url) {
                      setFormErrors((prev) => ({ ...prev, base_url: undefined }))
                    }
                  }}
                  placeholder="https://api.example.com/v1"
                  disabled={isUsingTemplate}
                  className={`${isUsingTemplate ? 'cursor-not-allowed bg-muted' : ''} ${formErrors.base_url ? 'border-destructive focus-visible:ring-destructive' : ''}`}
                />
                {formErrors.base_url && (
                  <p className="text-destructive text-xs">{formErrors.base_url}</p>
                )}
                {isUsingTemplate && !formErrors.base_url && (
                  <p className="text-xs text-muted-foreground">
                    使用模板时 URL 不可编辑,切换到"自定义"以手动配置
                  </p>
                )}
              </div>

              <div className="grid gap-2" data-tour="provider-apikey-input">
                <Label htmlFor="api_key" className={formErrors.api_key ? 'text-destructive' : ''}>
                  API Key *
                </Label>
                <div className="flex gap-2">
                  <Input
                    id="api_key"
                    type={showApiKey ? 'text' : 'password'}
                    value={editingProvider?.api_key || ''}
                    onChange={(e) => {
                      setEditingProvider((prev) =>
                        prev ? { ...prev, api_key: e.target.value } : null
                      )
                      if (formErrors.api_key) {
                        setFormErrors((prev) => ({ ...prev, api_key: undefined }))
                      }
                    }}
                    placeholder="sk-..."
                    className={`flex-1 ${formErrors.api_key ? 'border-destructive focus-visible:ring-destructive' : ''}`}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => setShowApiKey(!showApiKey)}
                    title={showApiKey ? '隐藏密钥' : '显示密钥'}
                  >
                    {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={copyApiKey}
                    title="复制密钥"
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                {formErrors.api_key && (
                  <p className="text-destructive text-xs">{formErrors.api_key}</p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="client_type">客户端类型</Label>
                <Select
                  value={editingProvider?.client_type || 'openai'}
                  onValueChange={(value) =>
                    setEditingProvider((prev) => (prev ? { ...prev, client_type: value } : null))
                  }
                  disabled={isUsingTemplate}
                >
                  <SelectTrigger
                    id="client_type"
                    className={isUsingTemplate ? 'cursor-not-allowed bg-muted' : ''}
                  >
                    <SelectValue placeholder="选择客户端类型" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="openai">OpenAI</SelectItem>
                    <SelectItem value="gemini">Gemini</SelectItem>
                  </SelectContent>
                </Select>
                {isUsingTemplate && (
                  <p className="text-xs text-muted-foreground">
                    使用模板时客户端类型不可编辑,切换到"自定义"以手动配置
                  </p>
                )}
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="grid gap-2">
                  <Label htmlFor="max_retry">最大重试</Label>
                  <Input
                    id="max_retry"
                    type="number"
                    min="0"
                    value={editingProvider?.max_retry ?? ''}
                    onChange={(e) => {
                      const val = e.target.value === '' ? null : parseInt(e.target.value)
                      setEditingProvider((prev) => (prev ? { ...prev, max_retry: val } : null))
                    }}
                    placeholder="默认: 2"
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="timeout">超时(秒)</Label>
                  <Input
                    id="timeout"
                    type="number"
                    min="1"
                    value={editingProvider?.timeout ?? ''}
                    onChange={(e) => {
                      const val = e.target.value === '' ? null : parseInt(e.target.value)
                      setEditingProvider((prev) => (prev ? { ...prev, timeout: val } : null))
                    }}
                    placeholder="默认: 30"
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="retry_interval">重试间隔(秒)</Label>
                  <Input
                    id="retry_interval"
                    type="number"
                    min="1"
                    value={editingProvider?.retry_interval ?? ''}
                    onChange={(e) => {
                      const val = e.target.value === '' ? null : parseInt(e.target.value)
                      setEditingProvider((prev) => (prev ? { ...prev, retry_interval: val } : null))
                    }}
                    placeholder="默认: 10"
                  />
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditDialogOpen(false)}
                data-tour="provider-cancel-button"
              >
                取消
              </Button>
              <Button type="submit" data-tour="provider-save-button">
                保存
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除确认对话框 */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除提供商 "{deletingIndex !== null ? providers[deletingIndex]?.name : ''}" 吗？
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
              确定要删除选中的 {selectedProviders.size} 个提供商吗？ 此操作无法撤销。
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
  )
}
