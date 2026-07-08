import { useState, useEffect, useCallback } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Package,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  Save,
  RotateCcw,
  Power,
  Loader2,
  Search,
  ArrowLeft,
  Info,
  Eye,
  EyeOff,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import {
  getInstalledPlugins,
  getPluginConfigSchema,
  getPluginConfig,
  updatePluginConfig,
  resetPluginConfig,
  togglePlugin,
  type InstalledPlugin,
  type PluginConfigSchema,
  type ConfigFieldSchema,
  type ConfigSectionSchema,
} from '@/lib/plugin-api'

// 字段渲染组件
interface FieldRendererProps {
  field: ConfigFieldSchema
  value: unknown
  onChange: (value: unknown) => void
  sectionName: string
}

function FieldRenderer({ field, value, onChange }: FieldRendererProps) {
  const [showPassword, setShowPassword] = useState(false)

  // 根据 ui_type 渲染不同的控件
  switch (field.ui_type) {
    case 'switch':
      return (
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label>{field.label}</Label>
            {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
          </div>
          <Switch checked={Boolean(value)} onCheckedChange={onChange} disabled={field.disabled} />
        </div>
      )

    case 'number':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Input
            type="number"
            value={(value as number) ?? field.default}
            onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
            min={field.min}
            max={field.max}
            step={field.step ?? 1}
            placeholder={field.placeholder}
            disabled={field.disabled}
          />
          {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
        </div>
      )

    case 'slider':
      return (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>{field.label}</Label>
            <span className="text-sm text-muted-foreground">
              {(value as number) ?? field.default}
            </span>
          </div>
          <Slider
            value={[(value as number) ?? (field.default as number)]}
            onValueChange={(v) => onChange(v[0])}
            min={field.min ?? 0}
            max={field.max ?? 100}
            step={field.step ?? 1}
            disabled={field.disabled}
          />
          {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
        </div>
      )

    case 'select':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Select
            value={String(value ?? field.default)}
            onValueChange={onChange}
            disabled={field.disabled}
          >
            <SelectTrigger>
              <SelectValue placeholder={field.placeholder ?? '请选择'} />
            </SelectTrigger>
            <SelectContent>
              {field.choices?.map((choice) => (
                <SelectItem key={String(choice)} value={String(choice)}>
                  {String(choice)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
        </div>
      )

    case 'textarea':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Textarea
            value={(value as string) ?? field.default}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            rows={field.rows ?? 3}
            disabled={field.disabled}
          />
          {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
        </div>
      )

    case 'password':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <div className="relative">
            <Input
              type={showPassword ? 'text' : 'password'}
              value={(value as string) ?? ''}
              onChange={(e) => onChange(e.target.value)}
              placeholder={field.placeholder}
              disabled={field.disabled}
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3"
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
          {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
        </div>
      )

    case 'text':
    default:
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Input
            type="text"
            value={(value as string) ?? field.default ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            maxLength={field.max_length}
            disabled={field.disabled}
          />
          {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
        </div>
      )
  }
}

// Section 渲染组件
interface SectionRendererProps {
  section: ConfigSectionSchema
  config: Record<string, unknown>
  onChange: (sectionName: string, fieldName: string, value: unknown) => void
}

function SectionRenderer({ section, config, onChange }: SectionRendererProps) {
  const [isOpen, setIsOpen] = useState(!section.collapsed)

  // 按 order 排序字段
  const sortedFields = Object.entries(section.fields)
    .filter(([, field]) => !field.hidden)
    .sort(([, a], [, b]) => a.order - b.order)

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div className="ios-group overflow-hidden">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="ios-row ios-touch min-h-[64px] w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                {isOpen ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[15px] font-medium leading-5">
                  {section.title}
                </span>
                {section.description && (
                  <span className="mt-1 block truncate text-[13px] leading-5 text-muted-foreground">
                    {section.description}
                  </span>
                )}
              </span>
            </span>
            <span className="shrink-0 text-[13px] leading-5 text-muted-foreground">
              {sortedFields.length} 项
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="divide-y divide-border/55">
            {sortedFields.map(([fieldName, field]) => (
              <div key={fieldName} className="px-4 py-4 sm:px-5">
                <FieldRenderer
                  field={field}
                  value={(config[section.name] as Record<string, unknown>)?.[fieldName]}
                  onChange={(value) => onChange(section.name, fieldName, value)}
                  sectionName={section.name}
                />
              </div>
            ))}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

// 插件配置编辑器
interface PluginConfigEditorProps {
  plugin: InstalledPlugin
  onBack: () => void
}

function PluginConfigEditor({ plugin, onBack }: PluginConfigEditorProps) {
  const { toast } = useToast()
  const [schema, setSchema] = useState<PluginConfigSchema | null>(null)
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [originalConfig, setOriginalConfig] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [resetDialogOpen, setResetDialogOpen] = useState(false)

  // 加载配置
  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const [schemaData, configData] = await Promise.all([
        getPluginConfigSchema(plugin.id),
        getPluginConfig(plugin.id),
      ])
      setSchema(schemaData)
      setConfig(configData)
      setOriginalConfig(JSON.parse(JSON.stringify(configData)))
    } catch (error) {
      toast({
        title: '加载配置失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [plugin.id, toast])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  // 检测配置变化
  useEffect(() => {
    setHasChanges(JSON.stringify(config) !== JSON.stringify(originalConfig))
  }, [config, originalConfig])

  // 处理字段变化
  const handleFieldChange = (sectionName: string, fieldName: string, value: unknown) => {
    setConfig((prev) => ({
      ...prev,
      [sectionName]: {
        ...((prev[sectionName] as Record<string, unknown>) || {}),
        [fieldName]: value,
      },
    }))
  }

  // 保存配置
  const handleSave = async () => {
    setSaving(true)
    try {
      await updatePluginConfig(plugin.id, config)
      setOriginalConfig(JSON.parse(JSON.stringify(config)))
      toast({
        title: '配置已保存',
        description: '更改将在插件重新加载后生效',
      })
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  // 重置配置
  const handleReset = async () => {
    try {
      await resetPluginConfig(plugin.id)
      toast({
        title: '配置已重置',
        description: '下次加载插件时将使用默认配置',
      })
      setResetDialogOpen(false)
      loadConfig()
    } catch (error) {
      toast({
        title: '重置失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 切换启用状态
  const handleToggle = async () => {
    try {
      const result = await togglePlugin(plugin.id)
      toast({
        title: result.message,
        description: result.note,
      })
      loadConfig()
    } catch (error) {
      toast({
        title: '切换状态失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  if (loading) {
    return (
      <div className="ios-empty-state min-h-[260px]">
        <span className="ios-empty-illustration">
          <Loader2 className="h-7 w-7 animate-spin text-primary" />
        </span>
        <span className="space-y-1.5">
          <span className="block text-[15px] font-semibold leading-5 text-foreground">
            正在加载配置
          </span>
          <span className="block text-[13px] leading-5 text-muted-foreground">
            正在读取插件配置项
          </span>
        </span>
      </div>
    )
  }

  if (!schema) {
    return (
      <div className="ios-empty-state min-h-[260px]">
        <span className="ios-empty-illustration">
          <AlertCircle className="h-7 w-7 text-primary" />
        </span>
        <span className="space-y-1.5">
          <span className="block text-[15px] font-semibold leading-5 text-foreground">
            无法加载配置
          </span>
          <span className="block text-[13px] leading-5 text-muted-foreground">
            返回插件列表后可以重新进入
          </span>
        </span>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 h-4 w-4" />
          返回
        </Button>
      </div>
    )
  }

  // 按 order 排序 sections
  const sortedSections = Object.values(schema.sections).sort((a, b) => a.order - b.order)

  // 获取当前启用状态
  const isEnabled = (config.plugin as Record<string, unknown>)?.enabled !== false

  const pluginTitle = plugin.manifest.name || schema.plugin_info.name || plugin.id
  const pluginVersion = schema.plugin_info.version || plugin.manifest.version

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 sm:space-y-6">
      {/* 头部 */}
      <div className="space-y-4">
        <button
          type="button"
          onClick={onBack}
          className="ios-touch inline-flex h-11 items-center gap-1.5 rounded-full px-3 text-[15px] font-medium text-primary hover:bg-accent/70 focus-visible:bg-accent/70 focus-visible:ring-0"
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2.5} />
          插件配置
        </button>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 max-w-full">
            <h1 className="ios-title ios-break-anywhere max-w-full text-[24px] leading-[1.12] sm:text-3xl">
              {pluginTitle}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[15px] leading-5">
              <span
                className={
                  isEnabled
                    ? 'inline-flex h-6 items-center rounded-full bg-[rgb(52_199_89_/_0.14)] px-2.5 text-[13px] font-medium text-[color:rgb(36_138_61)] dark:text-[color:rgb(99_230_131)]'
                    : 'inline-flex h-6 items-center rounded-full bg-muted px-2.5 text-[13px] font-medium text-muted-foreground'
                }
              >
                {isEnabled ? '已启用' : '已禁用'}
              </span>
              <span className="text-[15px] leading-5 text-muted-foreground">v{pluginVersion}</span>
            </div>
          </div>
          <div className="hidden gap-2 sm:flex">
            <Button variant="outline" size="sm" onClick={handleToggle}>
              <Power className="mr-2 h-4 w-4" />
              {isEnabled ? '禁用' : '启用'}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setResetDialogOpen(true)}>
              <RotateCcw className="mr-2 h-4 w-4" />
              重置
            </Button>
            <Button size="sm" onClick={handleSave} disabled={!hasChanges || saving}>
              {saving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              保存
            </Button>
          </div>
        </div>

        <div className="ios-group overflow-hidden sm:hidden">
          <button
            type="button"
            onClick={handleToggle}
            className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span
                className={`ios-symbol ios-symbol-sm ${isEnabled ? 'ios-symbol-red' : 'ios-symbol-green'}`}
              >
                <Power className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium leading-5">
                {isEnabled ? '禁用插件' : '启用插件'}
              </span>
            </span>
            <ChevronRight className="h-4 w-4 text-muted-foreground/70" />
          </button>
          <button
            type="button"
            onClick={() => setResetDialogOpen(true)}
            className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                <RotateCcw className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium leading-5">重置配置</span>
            </span>
            <ChevronRight className="h-4 w-4 text-muted-foreground/70" />
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-55 disabled:active:scale-100"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
              </span>
              <span className="text-[15px] font-medium leading-5">
                {saving ? '保存中' : '保存配置'}
              </span>
            </span>
            <span className="text-[13px] leading-5 text-muted-foreground">
              {hasChanges ? '待保存' : '已保存'}
            </span>
          </button>
        </div>
      </div>

      {/* 未保存提示 */}
      {hasChanges && (
        <div className="ios-group flex items-center gap-3 border-[rgb(255_149_0_/_0.22)] bg-[rgb(255_149_0_/_0.08)] px-4 py-3 text-[rgb(138_75_0)] dark:border-[rgb(255_159_10_/_0.28)] dark:bg-[rgb(255_159_10_/_0.12)] dark:text-[rgb(255_214_102)]">
          <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
            <Info className="h-4 w-4" />
          </span>
          <p className="text-[14px] leading-5">有未保存的更改</p>
        </div>
      )}

      {/* 配置区域 */}
      {schema.layout.type === 'tabs' && schema.layout.tabs.length > 0 ? (
        // 标签页布局
        <Tabs defaultValue={schema.layout.tabs[0]?.id}>
          <TabsList>
            {schema.layout.tabs.map((tab) => (
              <TabsTrigger key={tab.id} value={tab.id}>
                {tab.title}
                {tab.badge && (
                  <Badge variant="secondary" className="ml-2 text-xs">
                    {tab.badge}
                  </Badge>
                )}
              </TabsTrigger>
            ))}
          </TabsList>
          {schema.layout.tabs.map((tab) => (
            <TabsContent key={tab.id} value={tab.id} className="mt-4 space-y-4">
              {tab.sections.map((sectionName) => {
                const section = schema.sections[sectionName]
                if (!section) return null
                return (
                  <SectionRenderer
                    key={sectionName}
                    section={section}
                    config={config}
                    onChange={handleFieldChange}
                  />
                )
              })}
            </TabsContent>
          ))}
        </Tabs>
      ) : // 自动布局
      sortedSections.length > 0 ? (
        <div className="space-y-4">
          {sortedSections.map((section) => (
            <SectionRenderer
              key={section.name}
              section={section}
              config={config}
              onChange={handleFieldChange}
            />
          ))}
        </div>
      ) : (
        <div className="ios-group overflow-hidden">
          <div className="ios-empty-state">
            <span className="ios-empty-illustration">
              <Info className="h-7 w-7 text-primary" />
            </span>
            <span className="space-y-1.5">
              <span className="block text-[15px] font-semibold leading-5 text-foreground">
                暂无可视化配置
              </span>
              <span className="block text-[13px] leading-5 text-muted-foreground">
                此插件没有暴露可在 WebUI 中编辑的配置项。
              </span>
            </span>
          </div>
        </div>
      )}

      {/* 重置确认对话框 */}
      <Dialog open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认重置配置</DialogTitle>
            <DialogDescription>
              这将删除当前配置文件，下次加载插件时将使用默认配置。此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetDialogOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleReset}>
              确认重置
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// 主页面组件
export function PluginConfigPage() {
  const { toast } = useToast()
  const [plugins, setPlugins] = useState<InstalledPlugin[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPlugin, setSelectedPlugin] = useState<InstalledPlugin | null>(null)

  // 加载插件列表
  const loadPlugins = async () => {
    setLoading(true)
    try {
      const data = await getInstalledPlugins()
      setPlugins(data)
    } catch (error) {
      toast({
        title: '加载插件列表失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPlugins()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 过滤插件
  const filteredPlugins = plugins.filter((plugin) => {
    const query = searchQuery.toLowerCase()
    return (
      plugin.id.toLowerCase().includes(query) ||
      plugin.manifest.name.toLowerCase().includes(query) ||
      plugin.manifest.description?.toLowerCase().includes(query)
    )
  })

  // 统计数据
  const enabledCount = plugins.length // 暂时假设都启用
  const disabledCount = 0

  // 如果选中了插件，显示配置编辑器
  if (selectedPlugin) {
    return (
      <ScrollArea className="h-full">
        <div className="min-w-0 max-w-full overflow-hidden px-5 py-5 sm:p-6">
          <div className="mx-auto w-[calc(100vw-2.5rem)] max-w-4xl sm:w-full">
            <PluginConfigEditor plugin={selectedPlugin} onBack={() => setSelectedPlugin(null)} />
          </div>
        </div>
      </ScrollArea>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="min-w-0 max-w-full overflow-hidden px-5 py-5 sm:p-6">
        <div className="mx-auto w-[calc(100vw-2.5rem)] max-w-5xl space-y-5 sm:w-full sm:space-y-6">
          {/* 标题 */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="ios-title">插件配置</h1>
              <p className="ios-subtitle">管理和配置已安装的插件</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={loadPlugins}
              className="hidden sm:inline-flex"
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
          </div>

          <button
            type="button"
            onClick={loadPlugins}
            className="ios-group ios-touch flex w-full min-w-0 items-center justify-between gap-4 overflow-hidden px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden"
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[16px] font-normal leading-6">
                  刷新插件配置
                </span>
                <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                  更新插件列表和配置状态
                </span>
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>

          {/* 统计 */}
          <div className="ios-group overflow-hidden">
            <div className="ios-row min-h-[60px] px-4 py-3">
              <span className="flex min-w-0 flex-1 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                  <Package className="h-4 w-4" />
                </span>
                <span className="truncate text-[16px] font-medium leading-6">已安装插件</span>
              </span>
              <span className="shrink-0 text-[17px] font-semibold tabular-nums">
                {plugins.length}
              </span>
            </div>
            <div className="ios-row min-h-[60px] px-4 py-3">
              <span className="flex min-w-0 flex-1 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                  <CheckCircle2 className="h-4 w-4" />
                </span>
                <span className="truncate text-[16px] font-medium leading-6">已启用</span>
              </span>
              <span className="shrink-0 text-[17px] font-semibold tabular-nums">
                {enabledCount}
              </span>
            </div>
            <div className="ios-row min-h-[60px] px-4 py-3">
              <span className="flex min-w-0 flex-1 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                  <AlertCircle className="h-4 w-4" />
                </span>
                <span className="truncate text-[16px] font-medium leading-6">已禁用</span>
              </span>
              <span className="shrink-0 text-[17px] font-semibold tabular-nums">
                {disabledCount}
              </span>
            </div>
          </div>

          {/* 搜索框 */}
          <div className="ios-search-field">
            <Search className="pointer-events-none absolute left-3.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="搜索插件"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="ios-search-input"
            />
          </div>

          {/* 插件列表 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <h2 className="text-[13px] font-medium leading-5 text-muted-foreground">
                已安装的插件
              </h2>
              <span className="text-[13px] leading-5 text-muted-foreground">
                共 {filteredPlugins.length} 个
              </span>
            </div>
            <div className="ios-group overflow-hidden">
              {loading ? (
                <div className="ios-row ios-row-plain min-h-[132px] !justify-center text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin" />
                </div>
              ) : filteredPlugins.length === 0 ? (
                <div className="ios-empty-state">
                  <span className="ios-empty-illustration">
                    <Package className="h-7 w-7 text-primary" />
                  </span>
                  <span className="space-y-1.5">
                    <span className="block text-[15px] font-semibold leading-5 text-foreground">
                      {searchQuery ? '没有找到匹配的插件' : '暂无已安装的插件'}
                    </span>
                    <span className="block text-[13px] leading-5 text-muted-foreground">
                      {searchQuery ? '尝试其他搜索关键词' : '前往插件市场安装插件'}
                    </span>
                  </span>
                </div>
              ) : (
                filteredPlugins.map((plugin) => (
                  <button
                    key={plugin.id}
                    type="button"
                    className="ios-row ios-touch min-h-[76px] w-full min-w-0 overflow-hidden text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                    onClick={() => setSelectedPlugin(plugin)}
                  >
                    <span className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
                      <span className="ios-symbol ios-symbol-md ios-symbol-blue shrink-0">
                        <Package className="h-5 w-5" />
                      </span>
                      <span className="min-w-0 flex-1 overflow-hidden">
                        <span className="flex min-w-0 max-w-full items-center gap-2 overflow-hidden">
                          <span className="block min-w-0 flex-1 truncate text-[16px] font-medium leading-6">
                            {plugin.manifest.name}
                          </span>
                          <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[12px] font-medium leading-4 text-muted-foreground">
                            v{plugin.manifest.version}
                          </span>
                        </span>
                        <span className="mt-0.5 block min-w-0 max-w-full truncate text-[13px] leading-5 text-muted-foreground">
                          {plugin.manifest.description || '暂无描述'}
                        </span>
                      </span>
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </ScrollArea>
  )
}
