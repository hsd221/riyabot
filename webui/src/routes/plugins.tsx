import { useState, useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  Download,
  ExternalLink,
  Loader2,
  Search,
  Settings2,
  Tags,
  Star,
  RefreshCw,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { PluginInfo } from '@/types/plugin'
import {
  fetchPluginList,
  checkGitStatus,
  connectPluginProgressWebSocket,
  installPlugin,
  uninstallPlugin,
  updatePlugin,
  getMaimaiVersion,
  isPluginCompatible,
  getInstalledPlugins,
  checkPluginInstalled,
  getInstalledPluginVersion,
  type GitStatus,
  type PluginLoadProgress,
  type MaimaiVersion,
  type InstalledPlugin,
} from '@/lib/plugin-api'
import { useToast } from '@/hooks/use-toast'
import { Progress } from '@/components/ui/progress'
import { PluginStats } from '@/components/plugin-stats'
import { recordPluginDownload, getPluginStats, type PluginStatsData } from '@/lib/plugin-stats'

const starActiveClass = 'fill-[rgb(255_204_0)] text-[rgb(255_204_0)]'

// 分类名称映射
const CATEGORY_NAMES: Record<string, string> = {
  'Group Management': '群组管理',
  'Entertainment & Interaction': '娱乐互动',
  Entertainment: '娱乐互动',
  'Utility Tools': '实用工具',
  Utility: '实用工具',
  Tools: '实用工具',
  'Content Generation': '内容生成',
  Multimedia: '多媒体',
  'External Integration': '外部集成',
  'Data Analysis & Insights': '数据分析与洞察',
  'Core System': '核心系统',
  Other: '其他',
}

function getCategorySymbolColor(category: string) {
  const normalized = category.toLowerCase()

  if (normalized.includes('group')) return 'ios-symbol-blue'
  if (normalized.includes('entertain') || normalized.includes('interaction'))
    return 'ios-symbol-pink'
  if (normalized.includes('utility') || normalized.includes('tool')) return 'ios-symbol-green'
  if (normalized.includes('content') || normalized.includes('generation'))
    return 'ios-symbol-purple'
  if (
    normalized.includes('multimedia') ||
    normalized.includes('image') ||
    normalized.includes('audio')
  ) {
    return 'ios-symbol-purple'
  }
  if (normalized.includes('external') || normalized.includes('integration'))
    return 'ios-symbol-orange'
  if (
    normalized.includes('data') ||
    normalized.includes('analysis') ||
    normalized.includes('insight')
  ) {
    return 'ios-symbol-teal'
  }

  return 'ios-symbol-gray'
}

const CATEGORY_OPTIONS = [
  { value: 'all', label: '全部分类', description: '显示所有插件分类', color: 'ios-symbol-gray' },
  {
    value: 'Group Management',
    label: '群组管理',
    description: '群组相关管理能力',
    color: 'ios-symbol-blue',
  },
  {
    value: 'Entertainment & Interaction',
    label: '娱乐互动',
    description: '互动玩法与娱乐功能',
    color: 'ios-symbol-pink',
  },
  {
    value: 'Utility Tools',
    label: '实用工具',
    description: '效率工具与辅助能力',
    color: 'ios-symbol-green',
  },
  {
    value: 'Content Generation',
    label: '内容生成',
    description: '文本、图片等生成能力',
    color: 'ios-symbol-purple',
  },
  {
    value: 'Multimedia',
    label: '多媒体',
    description: '图片、音频与媒体处理',
    color: 'ios-symbol-purple',
  },
  {
    value: 'External Integration',
    label: '外部集成',
    description: '第三方服务与系统连接',
    color: 'ios-symbol-orange',
  },
  {
    value: 'Data Analysis & Insights',
    label: '数据分析与洞察',
    description: '统计分析与信息洞察',
    color: 'ios-symbol-teal',
  },
  { value: 'Other', label: '其他', description: '未归入固定分类的插件', color: 'ios-symbol-gray' },
] as const

type PluginViewTab = 'all' | 'installed' | 'updates'

const PLUGIN_VIEW_OPTIONS: Array<{
  value: PluginViewTab
  label: string
  description: string
  Icon: LucideIcon
  color: string
}> = [
  {
    value: 'all',
    label: '全部插件',
    description: '浏览所有符合筛选的插件',
    Icon: Star,
    color: 'ios-symbol-blue',
  },
  {
    value: 'installed',
    label: '已安装',
    description: '仅查看本地已安装插件',
    Icon: CheckCircle2,
    color: 'ios-symbol-green',
  },
  {
    value: 'updates',
    label: '可更新',
    description: '查看有新版可用的插件',
    Icon: RefreshCw,
    color: 'ios-symbol-orange',
  },
]

const PLUGIN_LOADING_ROWS = ['插件索引', '兼容性信息', '本地安装状态']

function getPluginOperationLabel(progress: PluginLoadProgress) {
  if (progress.operation === 'fetch') return '加载插件列表'
  if (progress.operation === 'install')
    return `安装插件${progress.plugin_id ? `: ${progress.plugin_id}` : ''}`
  if (progress.operation === 'uninstall')
    return `卸载插件${progress.plugin_id ? `: ${progress.plugin_id}` : ''}`
  if (progress.operation === 'update')
    return `更新插件${progress.plugin_id ? `: ${progress.plugin_id}` : ''}`
  return '处理插件'
}

function getFriendlyPluginError(message?: string | null) {
  const value = (message || '').trim()
  if (!value) return '插件列表暂时无法加载，请稍后重试。'

  if (/Unexpected token|is not valid JSON|Too Many R|Too Many Requests|请求频率过高/i.test(value)) {
    return '请求过于频繁，请稍后重试。'
  }

  if (/Failed to fetch|NetworkError|AbortError|Load failed|network|timeout/i.test(value)) {
    return '网络暂时不可用，请稍后重试。'
  }

  if (/HTTP error! status:\s*429/i.test(value)) {
    return '请求过于频繁，请稍后重试。'
  }

  return value.length > 96 ? `${value.slice(0, 96)}...` : value
}

function PluginLoadingState({ progress }: { progress: PluginLoadProgress | null }) {
  return (
    <div className="space-y-4">
      <div className="ios-group overflow-hidden">
        <div className="ios-row">
          <span className="flex min-w-0 items-center gap-3">
            <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
              <Loader2 className="h-4 w-4 animate-spin" />
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-medium leading-5">
                {progress ? getPluginOperationLabel(progress) : '加载插件列表'}
              </span>
              <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                {progress?.message || '正在同步插件市场数据'}
              </span>
            </span>
          </span>
          {progress ? (
            <span className="shrink-0 text-[14px] font-medium leading-5 text-muted-foreground">
              {progress.progress}%
            </span>
          ) : null}
        </div>
        {progress ? (
          <div className="border-t border-border/55 px-4 py-3 sm:px-5">
            <Progress value={progress.progress} className="h-1.5 bg-muted/70" />
            {progress.operation === 'fetch' && progress.total_plugins > 0 ? (
              <p className="mt-2 text-center text-[12px] leading-4 text-muted-foreground">
                已加载 {progress.loaded_plugins} / {progress.total_plugins} 个插件
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="ios-group overflow-hidden">
        {PLUGIN_LOADING_ROWS.map((label, index) => (
          <div key={label} className="ios-row min-h-[82px] justify-start gap-3 md:min-h-[92px]">
            <span className="h-9 w-9 shrink-0 animate-pulse rounded-[10px] bg-muted" />
            <span className="min-w-0 flex-1 space-y-2">
              <span className="block h-4 w-28 animate-pulse rounded-full bg-muted md:w-40" />
              <span className="block h-3 w-full max-w-[13rem] animate-pulse rounded-full bg-muted/80 md:max-w-[28rem]" />
            </span>
            {index === 0 ? (
              <span className="h-7 w-14 shrink-0 animate-pulse rounded-full bg-muted" />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}

export function PluginsPage() {
  const navigate = useNavigate()
  const [selectedPlugin, setSelectedPlugin] = useState<PluginInfo | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [activeTab, setActiveTab] = useState<PluginViewTab>('all')
  const [viewDialogOpen, setViewDialogOpen] = useState(false)
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false)
  const [showCompatibleOnly, setShowCompatibleOnly] = useState(true) // 默认只显示兼容的
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [loadProgress, setLoadProgress] = useState<PluginLoadProgress | null>(null)
  const [maimaiVersion, setMaimaiVersion] = useState<MaimaiVersion | null>(null)
  const [, setInstalledPlugins] = useState<InstalledPlugin[]>([])
  const [pluginStats, setPluginStats] = useState<Record<string, PluginStatsData>>({})
  const { toast } = useToast()

  // 加载插件统计数据
  const loadPluginStats = async (pluginList: PluginInfo[]) => {
    const statsPromises = pluginList.map(async (plugin) => {
      try {
        const stats = await getPluginStats(plugin.id)
        return { id: plugin.id, stats }
      } catch {
        return { id: plugin.id, stats: null }
      }
    })

    const results = await Promise.all(statsPromises)
    const statsMap: Record<string, PluginStatsData> = {}

    results.forEach(({ id, stats }) => {
      if (stats) {
        statsMap[id] = stats
      }
    })

    setPluginStats(statsMap)
  }

  // 统一管理 WebSocket 和数据加载
  useEffect(() => {
    let ws: WebSocket | null = null
    let isUnmounted = false

    const init = async () => {
      // 1. 先连接 WebSocket
      ws = connectPluginProgressWebSocket(
        (progress) => {
          if (isUnmounted) return

          setLoadProgress(progress)

          // 如果加载完成，清除进度
          if (progress.stage === 'success') {
            setTimeout(() => {
              if (!isUnmounted) {
                setLoadProgress(null)
              }
            }, 2000)
          } else if (progress.stage === 'error') {
            setLoading(false)
            setError(progress.error || '加载失败')
          }
        },
        (error) => {
          console.error('WebSocket error:', error)
          if (!isUnmounted) {
            toast({
              title: 'WebSocket 连接失败',
              description: '无法实时显示加载进度',
              variant: 'destructive',
            })
          }
        }
      )

      // 2. 等待 WebSocket 连接建立
      await new Promise<void>((resolve) => {
        if (!ws) {
          resolve()
          return
        }

        const checkConnection = () => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            resolve()
          } else if (ws && ws.readyState === WebSocket.CLOSED) {
            resolve()
          } else {
            setTimeout(checkConnection, 100)
          }
        }

        checkConnection()
      })

      // 3. 检查 Git 状态
      if (!isUnmounted) {
        const status = await checkGitStatus()
        setGitStatus(status)

        if (!status.installed) {
          toast({
            title: 'Git 未安装',
            description: status.error || '请先安装 Git 才能使用插件安装功能',
            variant: 'destructive',
          })
        }
      }

      // 4. 获取主程序版本
      if (!isUnmounted) {
        const version = await getMaimaiVersion()
        setMaimaiVersion(version)
      }

      // 5. 加载插件列表（包含已安装信息）
      if (!isUnmounted) {
        try {
          setLoading(true)
          setError(null)
          const data = await fetchPluginList()

          if (!isUnmounted) {
            // 获取已安装插件列表
            const installed = await getInstalledPlugins()
            setInstalledPlugins(installed)

            // 将已安装信息合并到插件数据中
            const mergedData = data.map((plugin) => {
              const isInstalled = checkPluginInstalled(plugin.id, installed)
              const installedVersion = getInstalledPluginVersion(plugin.id, installed)

              return {
                ...plugin,
                installed: isInstalled,
                installed_version: installedVersion,
              }
            })

            // 添加本地安装但不在市场的插件
            for (const installedPlugin of installed) {
              const existsInMarket = mergedData.some((p) => p.id === installedPlugin.id)
              if (!existsInMarket && installedPlugin.manifest) {
                // 添加本地插件到列表
                mergedData.push({
                  id: installedPlugin.id,
                  manifest: {
                    manifest_version: installedPlugin.manifest.manifest_version || 1,
                    name: installedPlugin.manifest.name,
                    version: installedPlugin.manifest.version,
                    description: installedPlugin.manifest.description || '',
                    author: installedPlugin.manifest.author,
                    license: installedPlugin.manifest.license || 'Unknown',
                    host_application: installedPlugin.manifest.host_application,
                    homepage_url: installedPlugin.manifest.homepage_url,
                    repository_url: installedPlugin.manifest.repository_url,
                    keywords: installedPlugin.manifest.keywords || [],
                    categories: installedPlugin.manifest.categories || [],
                    default_locale: (installedPlugin.manifest.default_locale as string) || 'zh-CN',
                    locales_path: installedPlugin.manifest.locales_path as string | undefined,
                  },
                  downloads: 0,
                  rating: 0,
                  review_count: 0,
                  installed: true,
                  installed_version: installedPlugin.manifest.version,
                  published_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                })
              }
            }

            setPlugins(mergedData)

            // 6. 加载所有插件的统计数据
            loadPluginStats(mergedData)
          }
        } catch (err) {
          if (!isUnmounted) {
            const errorMessage = err instanceof Error ? err.message : '加载插件列表失败'
            setError(errorMessage)
            toast({
              title: '加载失败',
              description: errorMessage,
              variant: 'destructive',
            })
          }
        } finally {
          if (!isUnmounted) {
            setLoading(false)
          }
        }
      }
    }

    init()

    return () => {
      isUnmounted = true
      if (ws) {
        ws.close()
      }
    }
  }, [toast])

  // 获取插件状态徽章
  const getStatusBadge = (plugin: PluginInfo) => {
    // 优先显示兼容性状态
    if (!plugin.installed && maimaiVersion && !checkPluginCompatibility(plugin)) {
      return (
        <Badge
          variant="destructive"
          className="gap-1 border-0 bg-[rgb(255_59_48_/_0.14)] text-[color:rgb(201_52_43)] shadow-none dark:text-[color:rgb(255_105_97)]"
        >
          <AlertCircle className="h-3 w-3" />
          不兼容
        </Badge>
      )
    }

    if (plugin.installed) {
      // 版本比较：去除两边空格并进行比较
      const installedVer = plugin.installed_version?.trim()
      const marketVer = plugin.manifest.version?.trim()

      if (installedVer !== marketVer) {
        // 简单的版本比较：只有当市场版本比已安装版本新时才显示"可更新"
        // 如果本地版本更新（比如手动更新或市场数据过期），则显示"已安装"
        const installedParts = installedVer?.split('.').map(Number) || [0, 0, 0]
        const marketParts = marketVer?.split('.').map(Number) || [0, 0, 0]

        // 比较主版本号、次版本号、修订号
        for (let i = 0; i < 3; i++) {
          if ((marketParts[i] || 0) > (installedParts[i] || 0)) {
            // 市场版本更新
            return (
              <Badge
                variant="outline"
                className="gap-1 border-0 bg-[rgb(255_149_0_/_0.14)] text-[color:rgb(176_96_0)] shadow-none dark:text-[color:rgb(255_208_153)]"
              >
                <AlertCircle className="h-3 w-3" />
                可更新
              </Badge>
            )
          } else if ((marketParts[i] || 0) < (installedParts[i] || 0)) {
            // 本地版本更新
            break
          }
        }
      }

      return (
        <Badge
          variant="default"
          className="gap-1 border-0 bg-[rgb(52_199_89_/_0.14)] text-[color:rgb(36_138_61)] shadow-none dark:text-[color:rgb(99_230_131)]"
        >
          <CheckCircle2 className="h-3 w-3" />
          已安装
        </Badge>
      )
    }
    return null
  }

  // 检查插件兼容性
  const checkPluginCompatibility = (plugin: PluginInfo): boolean => {
    if (!maimaiVersion || !plugin.manifest?.host_application) return true

    return isPluginCompatible(
      plugin.manifest.host_application.min_version,
      plugin.manifest.host_application.max_version,
      maimaiVersion
    )
  }

  // 检查是否需要更新（市场版本比已安装版本新）
  const needsUpdate = (plugin: PluginInfo): boolean => {
    if (!plugin.installed || !plugin.installed_version || !plugin.manifest?.version) {
      return false
    }

    const installedVer = plugin.installed_version.trim()
    const marketVer = plugin.manifest.version.trim()

    if (installedVer === marketVer) return false

    const installedParts = installedVer.split('.').map(Number)
    const marketParts = marketVer.split('.').map(Number)

    // 比较主版本号、次版本号、修订号
    for (let i = 0; i < 3; i++) {
      if ((marketParts[i] || 0) > (installedParts[i] || 0)) {
        return true // 市场版本更新
      } else if ((marketParts[i] || 0) < (installedParts[i] || 0)) {
        return false // 本地版本更新
      }
    }

    return false
  }

  const matchesBaseFilters = (plugin: PluginInfo) => {
    // 跳过没有 manifest 的插件
    if (!plugin.manifest) {
      return false
    }

    // 搜索过滤
    const matchesSearch =
      searchQuery === '' ||
      plugin.manifest.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      plugin.manifest.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (plugin.manifest.keywords &&
        plugin.manifest.keywords.some((k) => k.toLowerCase().includes(searchQuery.toLowerCase())))

    // 分类过滤
    const matchesCategory =
      categoryFilter === 'all' ||
      (plugin.manifest.categories && plugin.manifest.categories.includes(categoryFilter))

    // 兼容性过滤
    const matchesCompatibility =
      !showCompatibleOnly || !maimaiVersion || checkPluginCompatibility(plugin)

    return matchesSearch && matchesCategory && matchesCompatibility
  }

  const getPluginViewCount = (view: PluginViewTab) =>
    plugins.filter((plugin) => {
      if (!matchesBaseFilters(plugin)) return false
      if (view === 'installed') return plugin.installed === true
      if (view === 'updates') return plugin.installed === true && needsUpdate(plugin)
      return true
    }).length

  const activePluginView =
    PLUGIN_VIEW_OPTIONS.find((item) => item.value === activeTab) ?? PLUGIN_VIEW_OPTIONS[0]
  const activeCategory =
    CATEGORY_OPTIONS.find((item) => item.value === categoryFilter) ?? CATEGORY_OPTIONS[0]

  // 过滤插件
  const filteredPlugins = plugins.filter((plugin) => {
    if (!matchesBaseFilters(plugin)) return false

    if (activeTab === 'installed') {
      return plugin.installed === true
    }
    if (activeTab === 'updates') {
      return plugin.installed === true && needsUpdate(plugin)
    }

    return true
  })

  const getPluginCategoryValue = (plugin: PluginInfo) => plugin.manifest?.categories?.[0] || 'Other'

  const getPluginCategoryLabel = (plugin: PluginInfo) => {
    const category = getPluginCategoryValue(plugin)
    return CATEGORY_NAMES[category] || category
  }

  const getPluginCategoryColor = (plugin: PluginInfo) => {
    const category = getPluginCategoryValue(plugin)
    return (
      CATEGORY_OPTIONS.find((item) => item.value === category)?.color ??
      getCategorySymbolColor(category)
    )
  }

  const getPluginDownloads = (plugin: PluginInfo) =>
    (pluginStats[plugin.id]?.downloads ?? plugin.downloads ?? 0).toLocaleString()

  const getPluginRating = (plugin: PluginInfo) =>
    (pluginStats[plugin.id]?.rating ?? plugin.rating ?? 0).toFixed(1)

  // 关闭对话框
  const closeDialog = () => {
    setSelectedPlugin(null)
  }

  // 安装插件处理
  const handleInstall = async (plugin: PluginInfo) => {
    if (!gitStatus?.installed) {
      toast({
        title: '无法安装',
        description: 'Git 未安装',
        variant: 'destructive',
      })
      return
    }

    // 检查插件兼容性
    if (maimaiVersion && !checkPluginCompatibility(plugin)) {
      toast({
        title: '无法安装',
        description: '插件与当前主程序版本不兼容',
        variant: 'destructive',
      })
      return
    }

    try {
      await installPlugin(plugin.id, plugin.manifest.repository_url || '', 'main')

      // 记录下载统计
      recordPluginDownload(plugin.id).catch(() => {})

      toast({
        title: '安装成功',
        description: `${plugin.manifest.name} 已成功安装`,
      })

      // 重新加载已安装插件列表
      const installed = await getInstalledPlugins()
      setInstalledPlugins(installed)

      // 重新合并已安装信息到插件列表
      setPlugins((prevPlugins) =>
        prevPlugins.map((p) => {
          if (p.id === plugin.id) {
            const isInstalled = checkPluginInstalled(p.id, installed)
            const installedVersion = getInstalledPluginVersion(p.id, installed)

            return {
              ...p,
              installed: isInstalled,
              installed_version: installedVersion,
            }
          }
          return p
        })
      )
    } catch (error) {
      toast({
        title: '安装失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 卸载插件处理
  const handleUninstall = async (plugin: PluginInfo) => {
    try {
      await uninstallPlugin(plugin.id)

      toast({
        title: '卸载成功',
        description: `${plugin.manifest.name} 已成功卸载`,
      })

      // 重新加载已安装插件列表
      const installed = await getInstalledPlugins()
      setInstalledPlugins(installed)

      // 重新合并已安装信息到插件列表
      setPlugins((prevPlugins) =>
        prevPlugins.map((p) => {
          if (p.id === plugin.id) {
            const isInstalled = checkPluginInstalled(p.id, installed)
            const installedVersion = getInstalledPluginVersion(p.id, installed)

            return {
              ...p,
              installed: isInstalled,
              installed_version: installedVersion,
            }
          }
          return p
        })
      )
    } catch (error) {
      toast({
        title: '卸载失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 更新插件处理
  const handleUpdate = async (plugin: PluginInfo) => {
    if (!gitStatus?.installed) {
      toast({
        title: '无法更新',
        description: 'Git 未安装',
        variant: 'destructive',
      })
      return
    }

    try {
      const result = await updatePlugin(plugin.id, plugin.manifest.repository_url || '', 'main')

      toast({
        title: '更新成功',
        description: `${plugin.manifest.name} 已从 ${result.old_version} 更新到 ${result.new_version}`,
      })

      // 重新加载已安装插件列表
      const installed = await getInstalledPlugins()
      setInstalledPlugins(installed)

      // 重新合并已安装信息到插件列表
      setPlugins((prevPlugins) =>
        prevPlugins.map((p) => {
          if (p.id === plugin.id) {
            const isInstalled = checkPluginInstalled(p.id, installed)
            const installedVersion = getInstalledPluginVersion(p.id, installed)

            return {
              ...p,
              installed: isInstalled,
              installed_version: installedVersion,
            }
          }
          return p
        })
      )
    } catch (error) {
      toast({
        title: '更新失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  return (
    <ScrollArea className="h-full w-full max-w-full overflow-x-hidden">
      <div className="ios-page w-screen max-w-full overflow-x-hidden sm:w-full">
        <div className="ios-content min-w-0 max-w-full">
          {/* 标题 */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="ios-title">插件市场</h1>
              <p className="ios-subtitle">浏览和管理插件</p>
            </div>
            <Button
              className="hidden sm:inline-flex"
              onClick={() => navigate({ to: '/plugin-mirrors' })}
            >
              <Settings2 className="mr-2 h-4 w-4" />
              配置镜像源
            </Button>
          </div>

          <button
            type="button"
            className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left sm:hidden"
            onClick={() => navigate({ to: '/plugin-mirrors' })}
          >
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                <Settings2 className="h-4 w-4" />
              </span>
              <span className="min-w-0">
                <span className="block text-[15px] font-medium leading-5 text-foreground">
                  镜像源
                </span>
                <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                  配置插件市场下载来源
                </span>
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>

          {/* Git 状态警告 */}
          {gitStatus && !gitStatus.installed && (
            <div className="ios-group overflow-hidden border-[rgb(255_149_0_/_0.24)] bg-[rgb(255_149_0_/_0.07)]">
              <div className="ios-row min-h-[86px] items-start">
                <span className="flex min-w-0 items-start gap-3">
                  <span className="ios-symbol ios-symbol-md ios-symbol-orange">
                    <AlertTriangle className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-semibold leading-5 text-[color:rgb(138_75_0)] dark:text-orange-100">
                      Git 未安装
                    </span>
                    <span className="mt-1 block text-[13px] leading-5 text-[color:rgb(138_75_0_/_0.8)] dark:text-orange-100/80">
                      {gitStatus.error || '请先安装 Git 才能使用插件安装功能'}
                    </span>
                    <span className="mt-2 block text-[13px] leading-5 text-[color:rgb(138_75_0_/_0.8)] dark:text-orange-100/80">
                      可从{' '}
                      <a
                        href="https://git-scm.com/downloads"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium text-[color:rgb(122_67_0)] underline underline-offset-2 dark:text-orange-100"
                      >
                        git-scm.com
                      </a>{' '}
                      下载并安装，安装完成后请重启主程序。
                    </span>
                  </span>
                </span>
              </div>
            </div>
          )}

          {/* 搜索和筛选栏 */}
          <div className="ios-group hidden overflow-hidden sm:block">
            <div className="ios-row ios-row-plain min-h-[68px] gap-4">
              <div className="ios-search-field min-w-0 flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="搜索插件..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="ios-search-input"
                />
              </div>
              <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                <SelectTrigger className="h-11 w-full max-w-[220px] rounded-[13px] border-0 bg-muted/80 shadow-[0_1px_0_rgba(255,255,255,0.56)_inset] focus:ring-ring/35">
                  <SelectValue placeholder="选择分类" />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <label className="ios-row ios-touch min-h-[62px] cursor-pointer">
              <span className="flex min-w-0 items-center gap-3">
                <span className={`ios-symbol ios-symbol-sm ${activeCategory.color}`}>
                  <Tags className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[15px] font-medium leading-5">兼容版本</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    只显示兼容当前版本的插件
                  </span>
                </span>
              </span>
              <Switch
                checked={showCompatibleOnly}
                onCheckedChange={(checked) => setShowCompatibleOnly(checked === true)}
              />
            </label>
          </div>

          <div className="ios-group overflow-hidden sm:hidden">
            <div className="flex min-h-[58px] items-center gap-3 border-b border-border/70 px-4 py-3">
              <Search className="h-5 w-5 shrink-0 text-muted-foreground" />
              <Input
                placeholder="搜索插件..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-9 border-0 bg-transparent px-0 text-[15px] shadow-none focus-visible:ring-0"
              />
            </div>
            <Dialog open={categoryDialogOpen} onOpenChange={setCategoryDialogOpen}>
              <DialogTrigger asChild>
                <button className="ios-touch flex min-h-[58px] w-full items-center justify-between gap-4 border-b border-border/70 px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0">
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5 text-foreground">
                      分类
                    </span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      {activeCategory.description}
                    </span>
                  </span>
                  <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <span className="truncate text-[15px] leading-5 text-foreground">
                      {activeCategory.label}
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0" />
                  </span>
                </button>
              </DialogTrigger>
              <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
                <DialogHeader className="px-5 pt-5">
                  <DialogTitle>插件分类</DialogTitle>
                  <DialogDescription>选择要浏览的插件分类</DialogDescription>
                </DialogHeader>
                <div className="ios-scrollbar-none max-h-[58vh] overflow-y-auto px-5">
                  <div className="ios-group overflow-hidden">
                    {CATEGORY_OPTIONS.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                        onClick={() => {
                          setCategoryFilter(item.value)
                          setCategoryDialogOpen(false)
                        }}
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span className={`ios-symbol ios-symbol-sm ${item.color}`}>
                            <Tags className="h-4 w-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-[16px] font-medium leading-6">
                              {item.label}
                            </span>
                            <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                              {item.description}
                            </span>
                          </span>
                        </span>
                        {categoryFilter === item.value ? (
                          <Check className="h-4 w-4 shrink-0 text-primary" />
                        ) : (
                          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </DialogContent>
            </Dialog>
            <label className="ios-touch flex min-h-[58px] items-center justify-between gap-4 px-4 py-3">
              <span className="min-w-0">
                <span className="block text-[15px] font-medium leading-5 text-foreground">
                  兼容版本
                </span>
                <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                  只显示兼容当前版本的插件
                </span>
              </span>
              <Switch
                checked={showCompatibleOnly}
                onCheckedChange={(checked) => setShowCompatibleOnly(checked === true)}
              />
            </label>
          </div>

          {/* 标签页 */}
          <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
            <DialogTrigger asChild>
              <button className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden">
                <span className="flex min-w-0 items-center gap-3">
                  <span className={`ios-symbol ios-symbol-sm ${activePluginView.color}`}>
                    <activePluginView.Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium leading-5 text-muted-foreground">
                      当前视图
                    </span>
                    <span className="block truncate text-[16px] font-medium leading-6">
                      {activePluginView.label}
                    </span>
                  </span>
                </span>
                <span className="flex items-center gap-2 text-muted-foreground">
                  <span className="text-[14px] leading-5">
                    {getPluginViewCount(activePluginView.value)}
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0" />
                </span>
              </button>
            </DialogTrigger>
            <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
              <DialogHeader className="px-5 pt-5">
                <DialogTitle>插件视图</DialogTitle>
                <DialogDescription>选择要浏览的插件范围</DialogDescription>
              </DialogHeader>
              <div className="px-5">
                <div className="ios-group overflow-hidden">
                  {PLUGIN_VIEW_OPTIONS.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                      onClick={() => {
                        setActiveTab(item.value)
                        setViewDialogOpen(false)
                      }}
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span className={`ios-symbol ios-symbol-sm ${item.color}`}>
                          <item.Icon className="h-4 w-4" />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-[16px] font-medium leading-6">
                            {item.label}
                          </span>
                          <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                            {item.description}
                          </span>
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2 text-muted-foreground">
                        <span className="text-[14px] leading-5">
                          {getPluginViewCount(item.value)}
                        </span>
                        {activeTab === item.value ? (
                          <Check className="h-4 w-4 text-primary" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </DialogContent>
          </Dialog>

          <Tabs
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as PluginViewTab)}
            className="hidden w-full sm:block"
          >
            <TabsList className="grid w-full grid-cols-3">
              {PLUGIN_VIEW_OPTIONS.map((item) => (
                <TabsTrigger key={item.value} value={item.value}>
                  {item.label} ({getPluginViewCount(item.value)})
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          {/* 进度条 - 统一显示所有操作的进度 */}
          {loadProgress && loadProgress.stage === 'loading' && !loading && (
            <div className="ios-group overflow-hidden">
              <div className="ios-row">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">
                      {getPluginOperationLabel(loadProgress)}
                    </span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      {loadProgress.message}
                    </span>
                  </span>
                </span>
                <span className="shrink-0 text-[14px] font-medium leading-5 text-muted-foreground">
                  {loadProgress.progress}%
                </span>
              </div>
              <div className="border-t border-border/55 px-4 py-3 sm:px-5">
                <Progress value={loadProgress.progress} className="h-1.5 bg-muted/70" />
              </div>
            </div>
          )}

          {/* 加载错误显示 */}
          {loadProgress && loadProgress.stage === 'error' && loadProgress.error && (
            <div className="ios-group overflow-hidden">
              <div className="ios-row">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-red">
                    <AlertTriangle className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">加载失败</span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      {getFriendlyPluginError(loadProgress.error)}
                    </span>
                  </span>
                </span>
              </div>
            </div>
          )}

          {/* 插件列表 */}
          {loading ? (
            <PluginLoadingState
              progress={loadProgress?.stage === 'loading' ? loadProgress : null}
            />
          ) : error ? (
            <div className="ios-group overflow-hidden">
              <div className="ios-row min-h-[92px] items-start">
                <span className="flex min-w-0 items-start gap-3">
                  <span className="ios-symbol ios-symbol-md ios-symbol-red">
                    <AlertTriangle className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">
                      插件列表加载失败
                    </span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      {getFriendlyPluginError(error)}
                    </span>
                  </span>
                </span>
                <Button onClick={() => window.location.reload()} size="sm" variant="outline">
                  重试
                </Button>
              </div>
            </div>
          ) : filteredPlugins.length === 0 ? (
            <div className="ios-group overflow-hidden">
              <div className="ios-empty-state">
                <span className="ios-empty-illustration">
                  <Search className="h-7 w-7 text-primary" />
                </span>
                <span className="space-y-1.5">
                  <span className="block text-[15px] font-semibold leading-5 text-foreground">
                    未找到插件
                  </span>
                  <span className="block text-[13px] leading-5 text-muted-foreground">
                    {searchQuery || categoryFilter !== 'all'
                      ? '尝试调整搜索条件或筛选器'
                      : '暂无可用插件'}
                  </span>
                </span>
              </div>
            </div>
          ) : (
            <div className="ios-group overflow-hidden">
              {filteredPlugins.map((plugin) => (
                <div
                  key={plugin.id}
                  className="ios-row min-h-[104px] min-w-0 items-start py-3 md:min-h-[112px] md:items-center md:py-4"
                >
                  <button
                    type="button"
                    onClick={() => setSelectedPlugin(plugin)}
                    className="ios-touch -ml-1 flex min-w-0 flex-1 items-start gap-3 rounded-[14px] p-1 text-left focus-visible:outline-none md:items-center md:gap-4"
                  >
                    <span
                      className={`ios-symbol h-12 w-12 rounded-[13px] md:h-14 md:w-14 md:rounded-[16px] ${getPluginCategoryColor(plugin)}`}
                    >
                      <Tags className="h-5 w-5 md:h-6 md:w-6" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="min-w-0 truncate text-[16px] font-semibold leading-6 md:text-[17px]">
                          {plugin.manifest?.name || plugin.id}
                        </span>
                        <span className="hidden shrink-0 md:inline-flex">
                          {getStatusBadge(plugin)}
                        </span>
                      </span>
                      <span className="mt-0.5 line-clamp-2 text-[13px] leading-[1.45] text-muted-foreground md:max-w-3xl md:text-[14px]">
                        {plugin.manifest?.description || '无描述'}
                      </span>
                      <span className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[12px] leading-4 text-muted-foreground md:text-[13px]">
                        <span className="truncate">{getPluginCategoryLabel(plugin)}</span>
                        <span className="shrink-0">v{plugin.manifest?.version || 'unknown'}</span>
                        <span className="hidden shrink-0 md:inline">
                          {plugin.manifest?.author?.name || 'Unknown'}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Download className="h-3 w-3 shrink-0" />
                          {getPluginDownloads(plugin)}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Star className={`h-3 w-3 shrink-0 ${starActiveClass}`} />
                          {getPluginRating(plugin)}
                        </span>
                      </span>
                      {plugin.manifest?.keywords && plugin.manifest.keywords.length > 0 && (
                        <span className="mt-2 hidden flex-wrap gap-1.5 md:flex">
                          {plugin.manifest.keywords.slice(0, 4).map((keyword) => (
                            <Badge key={keyword} variant="outline" className="text-xs">
                              {keyword}
                            </Badge>
                          ))}
                          {plugin.manifest.keywords.length > 4 && (
                            <Badge variant="outline" className="text-xs">
                              +{plugin.manifest.keywords.length - 4}
                            </Badge>
                          )}
                        </span>
                      )}
                    </span>
                  </button>

                  <div className="flex w-[4.25rem] shrink-0 items-start justify-end gap-2 pt-1.5 md:w-[13rem] md:items-center md:pt-0">
                    <Button
                      variant="outline"
                      size="sm"
                      className="hidden h-9 rounded-full px-4 text-xs font-semibold md:inline-flex"
                      onClick={() => setSelectedPlugin(plugin)}
                    >
                      详情
                    </Button>
                    {plugin.installed ? (
                      needsUpdate(plugin) ? (
                        <Button
                          size="sm"
                          className="h-8 rounded-full px-3 text-xs font-semibold md:h-9 md:px-4"
                          disabled={!gitStatus?.installed}
                          title={!gitStatus?.installed ? 'Git 未安装' : undefined}
                          onClick={() => handleUpdate(plugin)}
                        >
                          <RefreshCw className="mr-1 hidden h-4 w-4 md:block" />
                          更新
                        </Button>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          className="border-destructive/20 bg-destructive/5 text-destructive hover:bg-destructive/10 hover:text-destructive h-8 rounded-full px-3 text-xs font-semibold md:h-9 md:px-4"
                          disabled={!gitStatus?.installed}
                          title={!gitStatus?.installed ? 'Git 未安装' : undefined}
                          onClick={() => handleUninstall(plugin)}
                        >
                          卸载
                        </Button>
                      )
                    ) : (
                      <Button
                        size="sm"
                        className="h-8 rounded-full px-3 text-xs font-semibold shadow-[0_6px_14px_hsl(var(--primary)_/_0.18)] md:h-9 md:px-4"
                        disabled={
                          !gitStatus?.installed ||
                          loadProgress?.operation === 'install' ||
                          (maimaiVersion !== null && !checkPluginCompatibility(plugin))
                        }
                        title={
                          !gitStatus?.installed
                            ? 'Git 未安装'
                            : maimaiVersion !== null && !checkPluginCompatibility(plugin)
                              ? `不兼容当前版本 (需要 ${plugin.manifest?.host_application?.min_version || '未知'}${plugin.manifest?.host_application?.max_version ? ` - ${plugin.manifest.host_application.max_version}` : '+'}，当前 ${maimaiVersion?.version})`
                              : undefined
                        }
                        onClick={() => handleInstall(plugin)}
                      >
                        <Download className="mr-1 hidden h-4 w-4 md:block" />
                        {loadProgress?.operation === 'install' &&
                        loadProgress?.plugin_id === plugin.id
                          ? '安装中'
                          : '获取'}
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 插件详情对话框 */}
          <Dialog open={selectedPlugin !== null} onOpenChange={closeDialog}>
            {selectedPlugin && selectedPlugin.manifest && (
              <DialogContent className="ios-sheet bottom-0 top-auto flex max-h-[86vh] translate-y-0 flex-col overflow-hidden rounded-b-none rounded-t-[28px] p-0 sm:bottom-auto sm:top-[50%] sm:max-h-[80vh] sm:max-w-2xl sm:translate-y-[-50%] sm:rounded-[22px]">
                <ScrollArea className="flex-1 overflow-auto">
                  <div className="p-5 sm:p-6">
                    <DialogHeader>
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 space-y-2">
                          <DialogTitle className="text-[22px] sm:text-2xl">
                            {selectedPlugin.manifest.name}
                          </DialogTitle>
                          <DialogDescription>
                            作者: {selectedPlugin.manifest.author?.name || 'Unknown'}
                            {selectedPlugin.manifest.author?.url && (
                              <a
                                href={selectedPlugin.manifest.author.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="ml-2 text-primary hover:underline"
                              >
                                <ExternalLink className="inline h-3 w-3" />
                              </a>
                            )}
                          </DialogDescription>
                        </div>
                        <div className="flex flex-col gap-2">
                          {selectedPlugin.manifest.categories &&
                            selectedPlugin.manifest.categories[0] && (
                              <Badge variant="secondary">
                                {CATEGORY_NAMES[selectedPlugin.manifest.categories[0]] ||
                                  selectedPlugin.manifest.categories[0]}
                              </Badge>
                            )}
                          {getStatusBadge(selectedPlugin)}
                        </div>
                      </div>
                    </DialogHeader>

                    <div className="space-y-5 sm:space-y-6">
                      {/* 插件统计 */}
                      <div className="hidden sm:block">
                        <PluginStats pluginId={selectedPlugin.id} />
                      </div>

                      {/* 基本信息 */}
                      <div className="ios-group overflow-hidden">
                        <div className="ios-row min-h-[52px] py-2.5">
                          <span className="text-[15px] text-muted-foreground">版本</span>
                          <span className="max-w-[58%] text-right text-[15px] font-medium">
                            v{selectedPlugin.manifest?.version || 'unknown'}
                            {selectedPlugin.installed && selectedPlugin.installed_version ? (
                              <span className="ml-2 text-muted-foreground">
                                已安装 v{selectedPlugin.installed_version}
                              </span>
                            ) : null}
                          </span>
                        </div>
                        <div className="ios-row min-h-[52px] py-2.5">
                          <span className="text-[15px] text-muted-foreground">下载量</span>
                          <span className="text-right text-[15px] font-medium">
                            {getPluginDownloads(selectedPlugin).toLocaleString()}
                          </span>
                        </div>
                        <div className="ios-row min-h-[52px] py-2.5">
                          <span className="text-[15px] text-muted-foreground">评分</span>
                          <span className="flex items-center gap-1 text-right text-[15px] font-medium">
                            <Star className={`h-4 w-4 ${starActiveClass}`} />
                            {getPluginRating(selectedPlugin)}
                          </span>
                        </div>
                        <div className="ios-row min-h-[52px] py-2.5">
                          <span className="text-[15px] text-muted-foreground">许可证</span>
                          <span className="max-w-[58%] truncate text-right text-[15px] font-medium">
                            {selectedPlugin.manifest.license || 'Unknown'}
                          </span>
                        </div>
                        <div className="ios-row min-h-[52px] py-2.5">
                          <span className="text-[15px] text-muted-foreground">支持版本</span>
                          <span className="max-w-[58%] truncate text-right text-[15px] font-medium">
                            {selectedPlugin.manifest.host_application?.min_version || '未知'}
                            {selectedPlugin.manifest.host_application?.max_version
                              ? ` - ${selectedPlugin.manifest.host_application.max_version}`
                              : ' - 最新版本'}
                          </span>
                        </div>
                      </div>

                      {/* 标签 */}
                      <div>
                        <p className="mb-2 text-sm font-medium">关键词</p>
                        <div className="flex flex-wrap gap-2">
                          {selectedPlugin.manifest.keywords &&
                            selectedPlugin.manifest.keywords.map((keyword) => (
                              <Badge key={keyword} variant="outline">
                                {keyword}
                              </Badge>
                            ))}
                        </div>
                      </div>

                      {/* 详细描述 */}
                      {selectedPlugin.detailed_description && (
                        <div>
                          <p className="mb-2 text-sm font-medium">详细说明</p>
                          <p className="whitespace-pre-line text-sm text-muted-foreground">
                            {selectedPlugin.detailed_description}
                          </p>
                        </div>
                      )}

                      {/* 描述（如果没有详细描述） */}
                      {!selectedPlugin.detailed_description && (
                        <div>
                          <p className="mb-2 text-sm font-medium">说明</p>
                          <p className="text-sm text-muted-foreground">
                            {selectedPlugin.manifest.description || '无描述'}
                          </p>
                        </div>
                      )}

                      {/* 链接 */}
                      {(selectedPlugin.manifest.homepage_url ||
                        selectedPlugin.manifest.repository_url) && (
                        <div className="ios-group overflow-hidden">
                          {selectedPlugin.manifest.homepage_url && (
                            <button
                              type="button"
                              className="ios-row ios-touch min-h-[56px] w-full text-left"
                              onClick={() =>
                                window.open(selectedPlugin.manifest.homepage_url, '_blank')
                              }
                            >
                              <span className="text-[16px] font-medium leading-6">主页</span>
                              <span className="flex items-center gap-2 text-[15px] leading-6 text-muted-foreground">
                                打开
                                <ChevronRight className="h-4 w-4" />
                              </span>
                            </button>
                          )}
                          {selectedPlugin.manifest.repository_url && (
                            <button
                              type="button"
                              className="ios-row ios-touch min-h-[56px] w-full text-left"
                              onClick={() =>
                                window.open(selectedPlugin.manifest.repository_url, '_blank')
                              }
                            >
                              <span className="text-[16px] font-medium leading-6">仓库</span>
                              <span className="flex items-center gap-2 text-[15px] leading-6 text-muted-foreground">
                                打开
                                <ChevronRight className="h-4 w-4" />
                              </span>
                            </button>
                          )}
                        </div>
                      )}
                    </div>

                    <DialogFooter className="hidden sm:flex">
                      {selectedPlugin.manifest.homepage_url && (
                        <Button
                          onClick={() =>
                            window.open(selectedPlugin.manifest.homepage_url, '_blank')
                          }
                        >
                          <ExternalLink className="mr-2 h-4 w-4" />
                          访问主页
                        </Button>
                      )}
                      {selectedPlugin.manifest.repository_url && (
                        <Button
                          variant="outline"
                          onClick={() =>
                            window.open(selectedPlugin.manifest.repository_url, '_blank')
                          }
                        >
                          <ExternalLink className="mr-2 h-4 w-4" />
                          查看仓库
                        </Button>
                      )}
                    </DialogFooter>
                  </div>
                </ScrollArea>
              </DialogContent>
            )}
          </Dialog>
        </div>
      </div>
    </ScrollArea>
  )
}
