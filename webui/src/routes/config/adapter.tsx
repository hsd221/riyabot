import { useState, useRef, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'
import {
  Bot,
  Bug,
  ChevronRight,
  Info,
  Upload,
  Download,
  FileText,
  Forward as ForwardIcon,
  Trash2,
  FolderOpen,
  Save,
  RefreshCw,
  Package,
  Container,
  Check,
  MessageCircle,
  Mic2,
  Server,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/hooks/use-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  getSavedConfigPath,
  saveConfigPath,
  loadConfigFromPath,
  saveConfigToPath,
} from '@/lib/adapter-config-api'

interface AdapterConfig {
  inner: {
    version: string
  }
  nickname: {
    nickname: string
  }
  napcat_server: {
    host: string
    port: number
    token: string
    heartbeat_interval: number
  }
  maibot_server: {
    host: string
    port: number
    enable_api_server: boolean
    base_url: string
    api_key: string
  }
  chat: {
    group_list_type: 'whitelist' | 'blacklist'
    group_list: number[]
    private_list_type: 'whitelist' | 'blacklist'
    private_list: number[]
    ban_user_id: number[]
    ban_qq_bot: boolean
    enable_poke: boolean
  }
  voice: {
    use_tts: boolean
  }
  forward: {
    image_threshold: number
  }
  debug: {
    level: string
  }
}

const DEFAULT_CONFIG: AdapterConfig = {
  inner: {
    version: '0.1.3',
  },
  nickname: {
    nickname: '',
  },
  napcat_server: {
    host: 'localhost',
    port: 8095,
    token: '',
    heartbeat_interval: 30,
  },
  maibot_server: {
    host: 'localhost',
    port: 8000,
    enable_api_server: false,
    base_url: 'ws://127.0.0.1:18095/ws',
    api_key: 'riyabot',
  },
  chat: {
    group_list_type: 'whitelist',
    group_list: [],
    private_list_type: 'whitelist',
    private_list: [],
    ban_user_id: [],
    ban_qq_bot: false,
    enable_poke: true,
  },
  voice: {
    use_tts: false,
  },
  forward: {
    image_threshold: 3,
  },
  debug: {
    level: 'INFO',
  },
}

// 预设配置
const PRESETS = {
  oneclick: {
    name: '一键包',
    description: '使用一键包部署的适配器配置',
    path: '../Bot-NapCat-Adapter/config.toml',
    icon: Package,
  },
  docker: {
    name: 'Docker',
    description: 'Docker Compose 部署的适配器配置',
    path: '/Bot/adapters-config/config.toml',
    icon: Container,
  },
} as const

type PresetKey = keyof typeof PRESETS
type AdapterMode = 'upload' | 'path' | 'preset'
type AdapterConfigTab = 'napcat' | 'riyabot' | 'chat' | 'voice' | 'forward' | 'debug'

const MODE_OPTIONS: Array<{
  value: AdapterMode
  label: string
  description: string
  Icon: LucideIcon
  color: string
}> = [
  {
    value: 'preset',
    label: '预设模式',
    description: '使用预设的部署配置',
    Icon: Package,
    color: 'ios-symbol-blue',
  },
  {
    value: 'upload',
    label: '上传文件模式',
    description: '上传配置文件，编辑后下载并手动覆盖',
    Icon: Upload,
    color: 'ios-symbol-green',
  },
  {
    value: 'path',
    label: '指定路径模式',
    description: '指定配置文件路径，自动加载和保存',
    Icon: FolderOpen,
    color: 'ios-symbol-orange',
  },
]

const CONFIG_TABS: Array<{
  value: AdapterConfigTab
  label: string
  description: string
  Icon: LucideIcon
  color: string
}> = [
  {
    value: 'napcat',
    label: 'NapCat 连接',
    description: 'OneBot 服务地址与心跳',
    Icon: Server,
    color: 'ios-symbol-blue',
  },
  {
    value: 'riyabot',
    label: '主程序连接',
    description: 'WebSocket 与 API 服务',
    Icon: Bot,
    color: 'ios-symbol-green',
  },
  {
    value: 'chat',
    label: '聊天控制',
    description: '群聊、私聊与禁用名单',
    Icon: MessageCircle,
    color: 'ios-symbol-purple',
  },
  {
    value: 'voice',
    label: '语音设置',
    description: 'TTS 开关与语音能力',
    Icon: Mic2,
    color: 'ios-symbol-pink',
  },
  {
    value: 'forward',
    label: '转发消息',
    description: '图片阈值与转发策略',
    Icon: ForwardIcon,
    color: 'ios-symbol-orange',
  },
  {
    value: 'debug',
    label: '调试',
    description: '日志等级与诊断输出',
    Icon: Bug,
    color: 'ios-symbol-gray',
  },
]

export function AdapterConfigPage() {
  // 工作模式：'upload' = 上传文件模式, 'path' = 指定路径模式, 'preset' = 预设模式
  const [mode, setMode] = useState<AdapterMode>('upload')
  const [config, setConfig] = useState<AdapterConfig | null>(null)
  const [fileName, setFileName] = useState<string>('')
  const [configPath, setConfigPath] = useState<string>('')
  const [selectedPreset, setSelectedPreset] = useState<PresetKey>('oneclick')
  const [pathError, setPathError] = useState<string>('')
  const [isSaving, setIsSaving] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [showModeSwitchDialog, setShowModeSwitchDialog] = useState(false)
  const [showClearPathDialog, setShowClearPathDialog] = useState(false)
  const [pendingMode, setPendingMode] = useState<AdapterMode | null>(null)
  const [activeConfigTab, setActiveConfigTab] = useState<AdapterConfigTab>('napcat')
  const [configTabDialogOpen, setConfigTabDialogOpen] = useState(false)
  const [modeDialogOpen, setModeDialogOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { toast } = useToast()
  const saveTimeoutRef = useRef<number | null>(null)
  const activeModeItem = MODE_OPTIONS.find((item) => item.value === mode) ?? MODE_OPTIONS[0]
  const activeConfigTabItem =
    CONFIG_TABS.find((item) => item.value === activeConfigTab) ?? CONFIG_TABS[0]

  // 验证路径格式
  const validatePath = (path: string): { valid: boolean; error: string } => {
    if (!path.trim()) {
      return { valid: false, error: '路径不能为空' }
    }

    if (!path.toLowerCase().endsWith('.toml')) {
      return { valid: false, error: '文件必须是 .toml 格式' }
    }

    // 支持相对路径和绝对路径
    // Windows 绝对路径: C:\path\to\file.toml 或 \\server\share\file.toml
    const windowsPathRegex = /^([a-zA-Z]:\\|\\\\[^\\]+\\[^\\]+\\).+\.toml$/i
    // Linux/Unix 绝对路径: /path/to/file.toml 或 ~/path/to/file.toml
    const unixPathRegex = /^(\/|~\/).+\.toml$/i
    // 相对路径: ./path/to/file.toml 或 ../path/to/file.toml 或 path/to/file.toml
    const relativePathRegex = /^(\.{1,2}[\\/]|[^:\\/]).+\.toml$/i

    const isWindows = windowsPathRegex.test(path)
    const isUnix = unixPathRegex.test(path)
    const isRelative = relativePathRegex.test(path)

    if (!isWindows && !isUnix && !isRelative) {
      return {
        valid: false,
        error: '路径格式错误',
      }
    }

    // 检查路径中是否包含非法字符
    // eslint-disable-next-line no-control-regex
    const illegalChars = /[<>"|?*\x00-\x1F]/
    if (illegalChars.test(path)) {
      return { valid: false, error: '路径包含非法字符' }
    }

    return { valid: true, error: '' }
  }

  // 处理路径输入变化
  const handlePathChange = (value: string) => {
    setConfigPath(value)

    // 实时验证
    if (value.trim()) {
      const validation = validatePath(value)
      setPathError(validation.error)
    } else {
      setPathError('')
    }
  }

  // 从预设加载配置
  const handleLoadFromPreset = useCallback(
    async (presetKey: PresetKey, options: { silent?: boolean } = {}) => {
      const preset = PRESETS[presetKey]
      setIsLoading(true)
      try {
        const content = await loadConfigFromPath(preset.path)
        const parsedConfig = parseTOML(content)
        setConfig(parsedConfig)
        setSelectedPreset(presetKey)
        setConfigPath(preset.path)

        // 保存路径偏好
        await saveConfigPath(preset.path)

        if (!options.silent) {
          toast({
            title: '加载成功',
            description: `已从${preset.name}预设加载配置`,
          })
        }
      } catch (error) {
        console.error('加载预设配置失败:', error)
        toast({
          title: '加载失败',
          description: error instanceof Error ? error.message : '无法读取预设配置文件',
          variant: 'destructive',
        })
      } finally {
        setIsLoading(false)
      }
    },
    [toast]
  )

  // 从指定路径加载配置
  const handleLoadFromPath = useCallback(
    async (path: string, options: { silent?: boolean } = {}) => {
      // 验证路径
      const validation = validatePath(path)
      if (!validation.valid) {
        setPathError(validation.error)
        toast({
          title: '路径无效',
          description: validation.error,
          variant: 'destructive',
        })
        return
      }

      setPathError('')
      setIsLoading(true)
      try {
        const content = await loadConfigFromPath(path)
        const parsedConfig = parseTOML(content)
        setConfig(parsedConfig)
        setConfigPath(path)

        // 保存路径偏好
        await saveConfigPath(path)

        if (!options.silent) {
          toast({
            title: '加载成功',
            description: `已从配置文件加载`,
          })
        }
      } catch (error) {
        console.error('加载配置失败:', error)
        toast({
          title: '加载失败',
          description: error instanceof Error ? error.message : '无法读取配置文件',
          variant: 'destructive',
        })
      } finally {
        setIsLoading(false)
      }
    },
    [toast]
  )

  // 组件挂载时加载保存的路径
  useEffect(() => {
    const loadSavedPath = async () => {
      try {
        const savedPath = await getSavedConfigPath()
        if (savedPath && savedPath.path) {
          setConfigPath(savedPath.path)

          // 检查是否是预设路径
          const presetEntry = Object.entries(PRESETS).find(
            ([, preset]) => preset.path === savedPath.path
          )
          if (presetEntry) {
            setMode('preset')
            setSelectedPreset(presetEntry[0] as PresetKey)
            await handleLoadFromPreset(presetEntry[0] as PresetKey, { silent: true })
          } else {
            setMode('path')
            await handleLoadFromPath(savedPath.path, { silent: true })
          }
        }
      } catch (error) {
        console.error('加载保存的路径失败:', error)
      }
    }
    loadSavedPath()
  }, [handleLoadFromPath, handleLoadFromPreset])

  // 自动保存配置到路径（防抖）
  const autoSaveToPath = useCallback(
    (updatedConfig: AdapterConfig) => {
      if ((mode !== 'path' && mode !== 'preset') || !configPath) return

      // 清除之前的定时器
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }

      // 设置新的定时器（1秒后保存）
      saveTimeoutRef.current = setTimeout(async () => {
        setIsSaving(true)
        try {
          const tomlContent = generateTOML(updatedConfig)
          await saveConfigToPath(configPath, tomlContent)
          toast({
            title: '自动保存成功',
            description: '配置已保存到文件',
          })
        } catch (error) {
          console.error('自动保存失败:', error)
          toast({
            title: '自动保存失败',
            description: error instanceof Error ? error.message : '保存配置失败',
            variant: 'destructive',
          })
        } finally {
          setIsSaving(false)
        }
      }, 1000)
    },
    [mode, configPath, toast]
  )

  // 手动保存配置
  const handleManualSave = async () => {
    if (!config || !configPath) return

    // 再次验证路径
    const validation = validatePath(configPath)
    if (!validation.valid) {
      toast({
        title: '保存失败',
        description: validation.error,
        variant: 'destructive',
      })
      return
    }

    setIsSaving(true)
    try {
      const tomlContent = generateTOML(config)
      await saveConfigToPath(configPath, tomlContent)
      toast({
        title: '保存成功',
        description: '配置已保存到文件',
      })
    } catch (error) {
      console.error('保存失败:', error)
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '保存配置失败',
        variant: 'destructive',
      })
    } finally {
      setIsSaving(false)
    }
  }

  // 刷新配置（重新从文件加载）
  const handleRefresh = async () => {
    if (!configPath) return
    await handleLoadFromPath(configPath)
  }

  // 切换模式
  const handleModeChange = (newMode: AdapterMode) => {
    if (newMode === mode) return

    // 如果有未保存的配置，显示确认对话框
    if (config) {
      setPendingMode(newMode)
      setShowModeSwitchDialog(true)
      return
    }

    // 直接切换模式
    performModeSwitch(newMode)
  }

  // 执行模式切换
  const performModeSwitch = (newMode: AdapterMode) => {
    setConfig(null)
    setFileName('')
    setPathError('')
    setMode(newMode)

    // 如果切换到预设模式，自动加载默认预设
    if (newMode === 'preset') {
      handleLoadFromPreset('oneclick')
    }

    const modeNames = {
      upload: '现在可以上传配置文件',
      path: '现在可以指定配置文件路径',
      preset: '现在可以使用预设配置',
    }

    toast({
      title: '已切换模式',
      description: modeNames[newMode],
    })
  }

  // 确认模式切换
  const confirmModeSwitch = () => {
    if (pendingMode) {
      performModeSwitch(pendingMode)
      setPendingMode(null)
    }
    setShowModeSwitchDialog(false)
  }

  // 清空路径
  const handleClearPath = () => {
    if (config) {
      setShowClearPathDialog(true)
      return
    }

    // 直接清空
    performClearPath()
  }

  // 执行清空路径
  const performClearPath = () => {
    setConfigPath('')
    setConfig(null)
    setPathError('')
    toast({
      title: '已清空',
      description: '路径和配置已清空',
    })
  }

  // 确认清空路径
  const confirmClearPath = () => {
    performClearPath()
    setShowClearPathDialog(false)
  }

  // 解析 TOML 内容为配置对象
  const parseTOML = (content: string): AdapterConfig => {
    const config: AdapterConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG))
    const lines = content.split('\n')
    let currentSection = ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#')) continue

      // 检测节（支持带注释的节头）
      const sectionMatch = trimmed.match(/^\[(\w+)\]/)
      if (sectionMatch) {
        currentSection = sectionMatch[1]
        continue
      }

      // 解析键值对
      const kvMatch = trimmed.match(/^(\w+)\s*=\s*(.+)$/)
      if (kvMatch && currentSection) {
        const [, key, value] = kvMatch
        let cleanValue = value.trim()

        // 移除行内注释（处理所有情况）
        // 1. 对于引号字符串: "value" # comment -> "value"
        // 2. 对于数字/布尔值: 123 # comment -> 123
        // 3. 对于数组: [1,2,3] # comment -> [1,2,3]
        const quotedMatch = cleanValue.match(/^("[^"]*")/)
        if (quotedMatch) {
          // 引号字符串，只保留引号部分
          cleanValue = quotedMatch[1]
        } else {
          // 非引号值，移除 # 及其后的所有内容
          const commentIndex = cleanValue.indexOf('#')
          if (commentIndex !== -1) {
            cleanValue = cleanValue.substring(0, commentIndex).trim()
          }
        }

        // 解析值
        let parsedValue: string | number | boolean | number[]
        if (cleanValue === 'true') {
          parsedValue = true
        } else if (cleanValue === 'false') {
          parsedValue = false
        } else if (cleanValue.startsWith('[') && cleanValue.endsWith(']')) {
          // 解析数组
          const arrayContent = cleanValue.slice(1, -1).trim()
          if (arrayContent) {
            const arrayValues = arrayContent.split(',').map((v) => {
              const trimmedV = v.trim()
              return isNaN(Number(trimmedV)) ? trimmedV.replace(/"/g, '') : Number(trimmedV)
            })
            // 确保数组类型一致（全部是数字或全部是字符串）
            const firstType = typeof arrayValues[0]
            parsedValue = arrayValues.every((v) => typeof v === firstType)
              ? (arrayValues as number[])
              : (arrayValues.filter((v) => typeof v === 'number') as number[])
          } else {
            parsedValue = []
          }
        } else if (cleanValue.startsWith('"') && cleanValue.endsWith('"')) {
          parsedValue = cleanValue.slice(1, -1)
        } else if (!isNaN(Number(cleanValue))) {
          parsedValue = Number(cleanValue)
        } else {
          parsedValue = cleanValue.replace(/"/g, '')
        }

        // 设置到配置对象
        if (currentSection in config) {
          const section = config[currentSection as keyof AdapterConfig] as Record<string, unknown>
          section[key] = parsedValue
        }
      }
    }

    return config
  }

  // 将配置对象转换为 TOML 格式（空值使用默认值填充）
  const generateTOML = (config: AdapterConfig): string => {
    const lines: string[] = []

    // 填充默认值的辅助函数
    const fillDefaults = (
      value: string | number,
      defaultValue: string | number
    ): string | number => {
      if (value === '' || value === null || value === undefined) {
        return defaultValue
      }
      return value
    }

    // Inner section
    lines.push('[inner]')
    lines.push(
      `version = "${fillDefaults(config.inner.version, DEFAULT_CONFIG.inner.version)}" # 版本号`
    )
    lines.push('# 请勿修改版本号，除非你知道自己在做什么')
    lines.push('')

    // Nickname section
    lines.push('[nickname] # 现在没用')
    lines.push(
      `nickname = "${fillDefaults(config.nickname.nickname, DEFAULT_CONFIG.nickname.nickname)}"`
    )
    lines.push('')

    // Napcat server section
    lines.push('[napcat_server] # Napcat连接的ws服务设置')
    lines.push(
      `host = "${fillDefaults(config.napcat_server.host, DEFAULT_CONFIG.napcat_server.host)}"      # Napcat设定的主机地址`
    )
    lines.push(
      `port = ${fillDefaults(config.napcat_server.port || 0, DEFAULT_CONFIG.napcat_server.port)}             # Napcat设定的端口`
    )
    lines.push(
      `token = "${fillDefaults(config.napcat_server.token, DEFAULT_CONFIG.napcat_server.token)}"              # Napcat设定的访问令牌，若无则留空`
    )
    lines.push(
      `heartbeat_interval = ${fillDefaults(config.napcat_server.heartbeat_interval || 0, DEFAULT_CONFIG.napcat_server.heartbeat_interval)} # 与Napcat设置的心跳相同（按秒计）`
    )
    lines.push('')

    // Main program server section
    lines.push('[maibot_server] # 连接主程序的ws服务设置')
    lines.push(
      `host = "${fillDefaults(config.maibot_server.host, DEFAULT_CONFIG.maibot_server.host)}" # 主程序在.env文件中设置的主机地址，即HOST字段`
    )
    lines.push(
      `port = ${fillDefaults(config.maibot_server.port || 0, DEFAULT_CONFIG.maibot_server.port)}        # 主程序在.env文件中设置的端口，即PORT字段`
    )
    lines.push(
      `enable_api_server = ${config.maibot_server.enable_api_server} # 是否启用API-Server模式连接`
    )
    lines.push(
      `base_url = "${fillDefaults(config.maibot_server.base_url, DEFAULT_CONFIG.maibot_server.base_url)}"             # API-Server连接地址 (ws://ip:port/path)，仅在enable_api_server为true时使用`
    )
    lines.push(
      `api_key = "${fillDefaults(config.maibot_server.api_key, DEFAULT_CONFIG.maibot_server.api_key)}"        # API Key (仅在enable_api_server为true时使用)`
    )
    lines.push('')

    // Chat section
    lines.push('[chat] # 黑白名单功能')
    lines.push(
      `group_list_type = "${fillDefaults(config.chat.group_list_type, DEFAULT_CONFIG.chat.group_list_type)}" # 群组名单类型，可选为：whitelist, blacklist`
    )
    lines.push(`group_list = [${config.chat.group_list.join(', ')}]               # 群组名单`)
    lines.push('# 当group_list_type为whitelist时，只有群组名单中的群组可以聊天')
    lines.push('# 当group_list_type为blacklist时，群组名单中的任何群组无法聊天')
    lines.push(
      `private_list_type = "${fillDefaults(config.chat.private_list_type, DEFAULT_CONFIG.chat.private_list_type)}" # 私聊名单类型，可选为：whitelist, blacklist`
    )
    lines.push(`private_list = [${config.chat.private_list.join(', ')}]               # 私聊名单`)
    lines.push('# 当private_list_type为whitelist时，只有私聊名单中的用户可以聊天')
    lines.push('# 当private_list_type为blacklist时，私聊名单中的任何用户无法聊天')
    lines.push(
      `ban_user_id = [${config.chat.ban_user_id.join(', ')}]   # 全局禁止名单（全局禁止名单中的用户无法进行任何聊天）`
    )
    lines.push(`ban_qq_bot = ${config.chat.ban_qq_bot} # 是否屏蔽QQ官方机器人`)
    lines.push(`enable_poke = ${config.chat.enable_poke} # 是否启用戳一戳功能`)
    lines.push('')

    // Voice section
    lines.push('[voice] # 发送语音设置')
    lines.push(
      `use_tts = ${config.voice.use_tts} # 是否使用tts语音（请确保你配置了tts并有对应的adapter）`
    )
    lines.push('')

    // Forward section
    lines.push('[forward] # 转发消息处理设置')
    lines.push(
      `image_threshold = ${fillDefaults(config.forward.image_threshold || 0, DEFAULT_CONFIG.forward.image_threshold)} # 图片数量阈值：转发消息中图片数量超过此值时使用占位符(避免VLM处理卡死)`
    )
    lines.push('')

    // Debug section
    lines.push('[debug]')
    lines.push(
      `level = "${fillDefaults(config.debug.level, DEFAULT_CONFIG.debug.level)}" # 日志等级（DEBUG, INFO, WARNING, ERROR, CRITICAL）`
    )

    return lines.join('\n')
  }

  // 上传文件处理
  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string
        const parsedConfig = parseTOML(content)
        setConfig(parsedConfig)
        setFileName(file.name)
        toast({
          title: '上传成功',
          description: `已加载配置文件：${file.name}`,
        })
      } catch (error) {
        console.error('解析配置文件失败:', error)
        toast({
          title: '解析失败',
          description: '配置文件格式错误，请检查文件内容',
          variant: 'destructive',
        })
      }
    }
    reader.readAsText(file)
  }

  // 下载配置文件
  const handleDownload = () => {
    if (!config) return

    const tomlContent = generateTOML(config)
    const blob = new Blob([tomlContent], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fileName || 'config.toml'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    toast({
      title: '下载成功',
      description: '配置文件已下载，请手动覆盖并重启适配器',
    })
  }

  // 使用默认配置
  const handleUseDefault = () => {
    setConfig(JSON.parse(JSON.stringify(DEFAULT_CONFIG)))
    setFileName('config.toml')
    toast({
      title: '已加载默认配置',
      description: '可以开始编辑配置',
    })
  }

  return (
    <ScrollArea className="h-full">
      <div className="w-screen max-w-full overflow-hidden">
      <div className="ios-page box-border w-full max-w-full overflow-hidden">
        {/* 页面标题 */}
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="ios-title">适配器配置</h1>
            <p className="ios-subtitle">
              管理 QQ 适配器的配置文件。保存后仍需手动重启适配器。
            </p>
          </div>
        </div>

        {/* 模式选择 */}
        <section className="space-y-4">
          <Dialog open={modeDialogOpen} onOpenChange={setModeDialogOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left sm:hidden"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span
                    className={`ios-symbol ios-symbol-md ${activeModeItem.color}`}
                  >
                    <activeModeItem.Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-semibold leading-5">工作模式</span>
                    <span className="mt-0.5 block truncate text-[13px] leading-5 text-muted-foreground">
                      {activeModeItem.label} · {activeModeItem.description}
                    </span>
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </DialogTrigger>
            <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
              <DialogHeader className="px-5 pt-5">
                <DialogTitle>工作模式</DialogTitle>
                <DialogDescription>选择配置文件的管理方式</DialogDescription>
              </DialogHeader>
              <div className="px-5 pb-5">
                <div className="ios-group overflow-hidden">
                  {MODE_OPTIONS.map((option) => {
                    const selected = mode === option.value
                    return (
                      <button
                        key={option.value}
                        type="button"
                        className={`ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0 ${
                          selected ? 'bg-primary/5' : ''
                        }`}
                        onClick={() => {
                          handleModeChange(option.value)
                          setModeDialogOpen(false)
                        }}
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span
                            className={`ios-symbol ios-symbol-sm ${option.color}`}
                          >
                            <option.Icon className="h-4 w-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[15px] font-medium leading-5">
                              {option.label}
                            </span>
                            <span className="mt-0.5 block truncate text-[13px] leading-5 text-muted-foreground">
                              {option.description}
                            </span>
                          </span>
                        </span>
                        {selected ? (
                          <Check className="h-4 w-4 shrink-0 text-primary" />
                        ) : (
                          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            </DialogContent>
          </Dialog>

          <div className="hidden px-1 sm:block sm:px-0">
            <h2 className="text-[20px] font-semibold leading-7 tracking-normal">
              工作模式
            </h2>
            <p className="mt-1 text-[14px] leading-5 text-muted-foreground">
              选择配置文件的管理方式
            </p>
          </div>

          <div className="ios-group hidden overflow-hidden sm:block">
            {MODE_OPTIONS.map((option) => {
              const selected = mode === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  className={`ios-touch flex min-h-[66px] w-full items-center justify-between gap-4 border-b border-border/70 px-4 py-3 text-left last:border-b-0 hover:bg-accent/55 ${
                    selected ? 'bg-primary/5' : ''
                  }`}
                  aria-current={selected ? 'page' : undefined}
                  onClick={() => handleModeChange(option.value)}
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span
                      className={`ios-symbol ios-symbol-md ${option.color}`}
                    >
                      <option.Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[15px] font-semibold leading-5 text-foreground">
                        {option.label}
                      </span>
                      <span className="mt-0.5 block text-[13px] leading-5 text-muted-foreground">
                        {option.description}
                      </span>
                    </span>
                  </span>
                  {selected && <Check className="h-4 w-4 shrink-0 text-primary" />}
                </button>
              )
            })}
          </div>

          {/* 预设模式配置 */}
          {mode === 'preset' && (
            <div className="space-y-3">
              <Label className="px-1 text-sm md:text-base">选择部署方式</Label>
              <div className="ios-group overflow-hidden">
                {Object.entries(PRESETS).map(([key, preset]) => {
                  const Icon = preset.icon
                  const isSelected = selectedPreset === key
                  return (
                    <button
                      key={key}
                      type="button"
                      className={`ios-touch flex min-h-[68px] w-full items-center justify-between gap-4 border-b border-border/70 px-4 py-3 text-left last:border-b-0 hover:bg-accent/55 ${
                        isSelected ? 'bg-primary/5' : ''
                      }`}
                      onClick={() => {
                        setSelectedPreset(key as PresetKey)
                        handleLoadFromPreset(key as PresetKey)
                      }}
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span className="ios-symbol ios-symbol-md ios-symbol-purple">
                          <Icon className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[15px] font-semibold leading-5 text-foreground">
                            {preset.name}
                          </span>
                          <span className="mt-0.5 block text-[13px] leading-5 text-muted-foreground">
                            {preset.description}
                          </span>
                          <span className="mt-0.5 block break-all font-mono text-[12px] leading-5 text-muted-foreground">
                            {preset.path}
                          </span>
                        </span>
                      </span>
                      {isSelected && <Check className="h-4 w-4 shrink-0 text-primary" />}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 路径模式配置 */}
          {mode === 'path' && (
            <>
            <div className="ios-group overflow-hidden sm:hidden">
              <div className="ios-row min-h-[62px] py-3">
                <span className="min-w-0">
                  <span className="block text-[15px] font-medium leading-5">配置文件路径</span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {pathError || '指定本地 TOML 配置文件'}
                  </span>
                </span>
              </div>
              <div className="border-b border-border/70 px-4 pb-3">
                <Input
                  id="config-path-mobile"
                  value={configPath}
                  onChange={(e) => handlePathChange(e.target.value)}
                  placeholder="adapter/config.toml"
                  className={`h-11 rounded-[12px] border-0 bg-muted px-3 text-[16px] shadow-none focus-visible:ring-0 ${
                    pathError ? 'text-destructive' : ''
                  }`}
                />
              </div>
              <button
                type="button"
                onClick={() => handleLoadFromPath(configPath)}
                disabled={isLoading || !configPath || !!pathError}
                className="ios-row ios-touch w-full text-left disabled:opacity-60 focus-visible:bg-accent/70 focus-visible:ring-0"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                    <FolderOpen className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium leading-5">
                      {isLoading ? '加载中...' : '加载配置'}
                    </span>
                    <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                      从指定路径读取配置
                    </span>
                  </span>
                </span>
                {isLoading ? (
                  <RefreshCw className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
                )}
              </button>
              <details className="group">
                <summary className="ios-row ios-touch cursor-pointer list-none text-left focus-visible:bg-accent/70 focus-visible:ring-0 [&::-webkit-details-marker]:hidden">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="ios-symbol ios-symbol-sm ios-symbol-gray">
                      <Info className="h-4 w-4" />
                    </span>
                    <span className="text-[15px] font-medium leading-5">路径格式说明</span>
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70 transition-transform group-open:rotate-90" />
                </summary>
                <div className="space-y-3 px-4 pb-4 pl-[4rem] text-[12px] leading-5 text-muted-foreground">
                  <div>
                    <span className="font-medium text-foreground">Windows</span>
                    <p className="break-all font-mono">C:\Adapter\config.toml</p>
                  </div>
                  <div>
                    <span className="font-medium text-foreground">Linux</span>
                    <p className="break-all font-mono">/opt/adapter/config.toml</p>
                  </div>
                  <p>修改后会自动保存到指定文件。</p>
                </div>
              </details>
            </div>

            <div className="ios-group hidden space-y-3 p-4 sm:block">
              <div className="space-y-2">
                <Label htmlFor="config-path" className="text-sm md:text-base">
                  配置文件路径
                </Label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <div className="flex-1 space-y-1">
                    <Input
                      id="config-path"
                      value={configPath}
                      onChange={(e) => handlePathChange(e.target.value)}
                      placeholder="例: C:\Adapter\config.toml"
                      className={`text-sm ${pathError ? 'border-destructive' : ''}`}
                    />
                    {pathError && <p className="text-destructive text-xs">{pathError}</p>}
                  </div>
                  <Button
                    onClick={() => handleLoadFromPath(configPath)}
                    disabled={isLoading || !configPath || !!pathError}
                    className="w-full sm:w-auto"
                  >
                    {isLoading ? (
                      <>
                        <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                        <span className="sm:hidden">加载中...</span>
                      </>
                    ) : (
                      <>
                        <span className="sm:hidden">加载配置</span>
                        <span className="hidden sm:inline">加载</span>
                      </>
                    )}
                  </Button>
                </div>
              </div>

              <details className="group rounded-[16px] bg-muted/45 p-3">
                <summary className="flex cursor-pointer select-none list-none items-center justify-between text-xs font-medium">
                  <span>路径格式说明</span>
                  <svg
                    className="h-4 w-4 transition-transform group-open:rotate-180"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19 9l-7 7-7-7"
                    />
                  </svg>
                </summary>
                <div className="mt-2 space-y-2 text-xs text-muted-foreground">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="whitespace-nowrap rounded bg-background px-1.5 py-0.5 font-mono text-[10px] md:text-xs">
                        Windows
                      </span>
                    </div>
                    <div className="space-y-0.5 break-all pl-2 text-[10px] md:text-xs">
                      <div>C:\Adapter\config.toml</div>
                      <div className="hidden sm:block">D:\Bot\adapter\config.toml</div>
                      <div className="hidden sm:block">\\server\share\config.toml</div>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="whitespace-nowrap rounded bg-background px-1.5 py-0.5 font-mono text-[10px] md:text-xs">
                        Linux
                      </span>
                    </div>
                    <div className="space-y-0.5 break-all pl-2 text-[10px] md:text-xs">
                      <div>/opt/adapter/config.toml</div>
                      <div className="hidden sm:block">/home/user/adapter/config.toml</div>
                      <div className="hidden sm:block">~/adapter/config.toml</div>
                    </div>
                  </div>
                  <p className="border-t pt-1 text-[10px] md:text-xs">
                    💡 配置会自动保存到指定文件，修改后 1 秒自动保存
                  </p>
                </div>
              </details>
            </div>
            </>
          )}
        </section>

        {/* 上传模式的操作按钮 */}
        {mode === 'upload' && !config && (
          <div className="flex w-full flex-col gap-2 sm:flex-row">
            <input
              ref={fileInputRef}
              type="file"
              accept=".toml"
              className="hidden"
              onChange={handleFileUpload}
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              size="sm"
              variant="outline"
              className="w-full sm:w-auto"
            >
              <Upload className="mr-2 h-4 w-4" />
              上传配置
            </Button>
            <Button onClick={handleUseDefault} size="sm" className="w-full sm:w-auto">
              <FileText className="mr-2 h-4 w-4" />
              使用默认配置
            </Button>
          </div>
        )}

        {/* 上传模式的下载按钮 */}
        {mode === 'upload' && config && (
          <div className="flex gap-2">
            <Button onClick={handleDownload} size="sm" className="w-full sm:w-auto">
              <Download className="mr-2 h-4 w-4" />
              下载配置
            </Button>
          </div>
        )}

        {/* 预设和路径模式的操作按钮 */}
        {(mode === 'preset' || mode === 'path') && config && (
          <>
          <div className="ios-group overflow-hidden sm:hidden">
            <button
              type="button"
              onClick={handleManualSave}
              disabled={isSaving || !!pathError}
              className="ios-row ios-touch w-full text-left disabled:opacity-60 focus-visible:bg-accent/70 focus-visible:ring-0"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                  <Save className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[15px] font-medium leading-5">
                    {isSaving ? '保存中...' : '立即保存'}
                  </span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    写入当前配置文件
                  </span>
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isLoading}
              className="ios-row ios-touch w-full text-left disabled:opacity-60 focus-visible:bg-accent/70 focus-visible:ring-0"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="ios-symbol ios-symbol-sm ios-symbol-teal">
                  <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
                </span>
                <span className="text-[15px] font-medium leading-5">刷新</span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
            </button>
            {mode === 'path' && (
              <button
                type="button"
                onClick={handleClearPath}
                className="ios-row ios-touch w-full text-left text-destructive focus-visible:bg-accent/70 focus-visible:ring-0"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span className="ios-symbol ios-symbol-sm ios-symbol-red">
                    <Trash2 className="h-4 w-4" />
                  </span>
                  <span className="text-[15px] font-medium leading-5">清空路径</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </button>
            )}
          </div>
          <div className="hidden flex-col gap-2 sm:flex sm:flex-row">
            <Button
              onClick={handleManualSave}
              size="sm"
              disabled={isSaving || !!pathError}
              className="w-full sm:w-auto"
            >
              <Save className="mr-2 h-4 w-4" />
              {isSaving ? '保存中...' : '立即保存'}
            </Button>
            <Button
              onClick={handleRefresh}
              size="sm"
              variant="outline"
              disabled={isLoading}
              className="w-full sm:w-auto"
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
            {mode === 'path' && (
              <Button
                onClick={handleClearPath}
                size="sm"
                variant="destructive"
                className="w-full sm:w-auto"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                清空路径
              </Button>
            )}
          </div>
          </>
        )}

        {/* 配置编辑区域 */}
        {!config ? (
          <div className="ios-group">
            <div className="ios-empty-state min-h-[260px]">
              <span className="ios-empty-illustration">
                <FileText className="relative z-10 h-7 w-7 text-primary" />
              </span>
              <div>
                <h3 className="text-[16px] font-semibold leading-6 text-foreground">
                  尚未加载配置
                </h3>
                <p className="mt-1 max-w-sm text-[13px] leading-5 text-muted-foreground">
                  {mode === 'preset'
                    ? '请选择预设的部署方式'
                    : mode === 'upload'
                      ? '请上传现有配置文件，或使用默认配置开始编辑'
                      : '请指定配置文件路径并点击加载按钮'}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <Tabs
            value={activeConfigTab}
            onValueChange={(value) => setActiveConfigTab(value as AdapterConfigTab)}
            className="w-full space-y-4"
          >
            <Dialog open={configTabDialogOpen} onOpenChange={setConfigTabDialogOpen}>
              <DialogTrigger asChild>
                <button className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0 sm:hidden">
                  <span className="flex min-w-0 items-center gap-3">
                    <span
                      className={`ios-symbol ios-symbol-sm flex-shrink-0 ${activeConfigTabItem.color}`}
                    >
                      <activeConfigTabItem.Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium leading-5 text-muted-foreground">
                        当前配置项
                      </span>
                      <span className="block truncate text-[16px] font-medium leading-6">
                        {activeConfigTabItem.label}
                      </span>
                    </span>
                  </span>
                  <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <span className="hidden max-w-[9rem] truncate text-[14px] leading-5 min-[390px]:block">
                      {activeConfigTabItem.description}
                    </span>
                    <ChevronRight className="h-4 w-4 flex-shrink-0" />
                  </span>
                </button>
              </DialogTrigger>
              <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
                <DialogHeader className="px-5 pt-5">
                  <DialogTitle>适配器配置项</DialogTitle>
                  <DialogDescription>选择要编辑的配置分组</DialogDescription>
                </DialogHeader>
                <div className="px-5">
                  <div className="ios-group overflow-hidden">
                    {CONFIG_TABS.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        className="ios-row ios-touch w-full text-left focus-visible:bg-accent/70 focus-visible:ring-0"
                        onClick={() => {
                          setActiveConfigTab(item.value)
                          setConfigTabDialogOpen(false)
                        }}
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span
                            className={`ios-symbol ios-symbol-sm flex-shrink-0 ${item.color}`}
                          >
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
                        <span className="flex items-center gap-2 text-muted-foreground">
                          {activeConfigTab === item.value ? (
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

            <div className="hidden overflow-x-auto pb-1 sm:block">
              <TabsList className="inline-flex w-auto min-w-full sm:grid sm:w-full sm:grid-cols-6">
                <TabsTrigger
                  value="napcat"
                  className="flex-shrink-0 whitespace-nowrap text-xs sm:text-sm"
                >
                  <span className="hidden sm:inline">Napcat 连接</span>
                  <span className="sm:hidden">Napcat</span>
                </TabsTrigger>
                <TabsTrigger
                  value="riyabot"
                  className="flex-shrink-0 whitespace-nowrap text-xs sm:text-sm"
                >
                  <span className="hidden sm:inline">主程序连接</span>
                  <span className="sm:hidden">主程序</span>
                </TabsTrigger>
                <TabsTrigger
                  value="chat"
                  className="flex-shrink-0 whitespace-nowrap text-xs sm:text-sm"
                >
                  <span className="hidden sm:inline">聊天控制</span>
                  <span className="sm:hidden">聊天</span>
                </TabsTrigger>
                <TabsTrigger
                  value="voice"
                  className="flex-shrink-0 whitespace-nowrap text-xs sm:text-sm"
                >
                  <span className="hidden sm:inline">语音设置</span>
                  <span className="sm:hidden">语音</span>
                </TabsTrigger>
                <TabsTrigger
                  value="forward"
                  className="flex-shrink-0 whitespace-nowrap text-xs sm:text-sm"
                >
                  <span className="hidden sm:inline">转发消息</span>
                  <span className="sm:hidden">转发</span>
                </TabsTrigger>
                <TabsTrigger
                  value="debug"
                  className="flex-shrink-0 whitespace-nowrap text-xs sm:text-sm"
                >
                  调试
                </TabsTrigger>
              </TabsList>
            </div>

            {/* Napcat 服务器配置 */}
            <TabsContent value="napcat" className="space-y-4">
              <NapcatServerSection
                config={config}
                onChange={(newConfig) => {
                  setConfig(newConfig)
                  autoSaveToPath(newConfig)
                }}
              />
            </TabsContent>

            {/* 主程序服务器配置 */}
            <TabsContent value="riyabot" className="space-y-4">
              <RiyaBotServerSection
                config={config}
                onChange={(newConfig) => {
                  setConfig(newConfig)
                  autoSaveToPath(newConfig)
                }}
              />
            </TabsContent>

            {/* 聊天控制配置 */}
            <TabsContent value="chat" className="space-y-4">
              <ChatControlSection
                config={config}
                onChange={(newConfig) => {
                  setConfig(newConfig)
                  autoSaveToPath(newConfig)
                }}
              />
            </TabsContent>

            {/* 语音配置 */}
            <TabsContent value="voice" className="space-y-4">
              <VoiceSection
                config={config}
                onChange={(newConfig) => {
                  setConfig(newConfig)
                  autoSaveToPath(newConfig)
                }}
              />
            </TabsContent>

            {/* 转发消息配置 */}
            <TabsContent value="forward" className="space-y-4">
              <ForwardSection
                config={config}
                onChange={(newConfig) => {
                  setConfig(newConfig)
                  autoSaveToPath(newConfig)
                }}
              />
            </TabsContent>

            {/* 调试配置 */}
            <TabsContent value="debug" className="space-y-4">
              <DebugSection
                config={config}
                onChange={(newConfig) => {
                  setConfig(newConfig)
                  autoSaveToPath(newConfig)
                }}
              />
            </TabsContent>
          </Tabs>
        )}

        {/* 模式切换确认对话框 */}
        <AlertDialog open={showModeSwitchDialog} onOpenChange={setShowModeSwitchDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认切换模式</AlertDialogTitle>
              <AlertDialogDescription>
                切换模式将清空当前配置，确定要继续吗？
                <br />
                <span className="text-destructive font-medium">请确保已保存重要配置</span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel
                onClick={() => {
                  setShowModeSwitchDialog(false)
                  setPendingMode(null)
                }}
              >
                取消
              </AlertDialogCancel>
              <AlertDialogAction onClick={confirmModeSwitch}>确认切换</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* 清空路径确认对话框 */}
        <AlertDialog open={showClearPathDialog} onOpenChange={setShowClearPathDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认清空路径</AlertDialogTitle>
              <AlertDialogDescription>
                清空路径将清除当前配置，确定要继续吗？
                <br />
                <span className="text-sm text-muted-foreground">
                  此操作不会删除配置文件，只是清除界面中的配置
                </span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => setShowClearPathDialog(false)}>
                取消
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={confirmClearPath}
                className="bg-destructive hover:bg-destructive/90"
              >
                确认清空
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      </div>
    </ScrollArea>
  )
}

const MOBILE_SETTING_INPUT_CLASS =
  'h-11 min-w-[8rem] max-w-[13rem] flex-1 border-0 bg-transparent px-0 py-0 text-right text-[16px] shadow-none focus-visible:bg-transparent focus-visible:ring-0'

function MobileSettingsSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <div className="space-y-2 md:hidden">
      <h3 className="px-1 text-[13px] font-medium leading-5 text-muted-foreground">
        {title}
      </h3>
      <div className="ios-group overflow-hidden">{children}</div>
    </div>
  )
}

function MobileSettingRow({
  htmlFor,
  label,
  description,
  children,
}: {
  htmlFor?: string
  label: string
  description?: string
  children: ReactNode
}) {
  return (
    <div className="ios-row min-h-[72px] py-3">
      <div className="min-w-0 flex-1 pr-3">
        <Label htmlFor={htmlFor} className="block text-[16px] font-medium leading-6">
          {label}
        </Label>
        {description && (
          <p className="mt-0.5 text-[13px] leading-5 text-muted-foreground">{description}</p>
        )}
      </div>
      {children}
    </div>
  )
}

// Napcat 服务器配置组件
function NapcatServerSection({
  config,
  onChange,
}: {
  config: AdapterConfig
  onChange: (config: AdapterConfig) => void
}) {
  return (
    <>
      <MobileSettingsSection title="Napcat WebSocket 服务">
        <MobileSettingRow
          htmlFor="napcat-host-mobile"
          label="主机地址"
          description="Napcat 设定的主机地址"
        >
          <Input
            id="napcat-host-mobile"
            value={config.napcat_server.host}
            onChange={(e) =>
              onChange({
                ...config,
                napcat_server: { ...config.napcat_server, host: e.target.value },
              })
            }
            placeholder="localhost"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
        <MobileSettingRow
          htmlFor="napcat-port-mobile"
          label="端口"
          description="留空使用默认值 8095"
        >
          <Input
            id="napcat-port-mobile"
            type="number"
            value={config.napcat_server.port || ''}
            onChange={(e) =>
              onChange({
                ...config,
                napcat_server: {
                  ...config.napcat_server,
                  port: e.target.value ? parseInt(e.target.value) : 0,
                },
              })
            }
            placeholder="8095"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
        <MobileSettingRow
          htmlFor="napcat-token-mobile"
          label="访问令牌"
          description="无令牌时可留空"
        >
          <Input
            id="napcat-token-mobile"
            type="password"
            value={config.napcat_server.token}
            onChange={(e) =>
              onChange({
                ...config,
                napcat_server: { ...config.napcat_server, token: e.target.value },
              })
            }
            placeholder="留空"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
        <MobileSettingRow
          htmlFor="napcat-heartbeat-mobile"
          label="心跳间隔"
          description="与 NapCat 设置保持一致"
        >
          <Input
            id="napcat-heartbeat-mobile"
            type="number"
            value={config.napcat_server.heartbeat_interval || ''}
            onChange={(e) =>
              onChange({
                ...config,
                napcat_server: {
                  ...config.napcat_server,
                  heartbeat_interval: e.target.value ? parseInt(e.target.value) : 0,
                },
              })
            }
            placeholder="30"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
      </MobileSettingsSection>

      <div className="hidden ios-group space-y-4 p-4 md:block md:space-y-6 md:p-6">
        <h3 className="mb-3 text-base font-semibold md:mb-4 md:text-lg">
          Napcat WebSocket 服务设置
        </h3>
        <div className="grid gap-3 md:gap-4">
          <div className="grid gap-2">
            <Label htmlFor="napcat-host" className="text-sm md:text-base">
              主机地址
            </Label>
            <Input
              id="napcat-host"
              value={config.napcat_server.host}
              onChange={(e) =>
                onChange({
                  ...config,
                  napcat_server: { ...config.napcat_server, host: e.target.value },
                })
              }
              placeholder="localhost"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">Napcat 设定的主机地址</p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="napcat-port" className="text-sm md:text-base">
              端口
            </Label>
            <Input
              id="napcat-port"
              type="number"
              value={config.napcat_server.port || ''}
              onChange={(e) =>
                onChange({
                  ...config,
                  napcat_server: {
                    ...config.napcat_server,
                    port: e.target.value ? parseInt(e.target.value) : 0,
                  },
                })
              }
              placeholder="8095"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">
              Napcat 设定的端口（留空使用默认值 8095）
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="napcat-token" className="text-sm md:text-base">
              访问令牌（Token）
            </Label>
            <Input
              id="napcat-token"
              type="password"
              value={config.napcat_server.token}
              onChange={(e) =>
                onChange({
                  ...config,
                  napcat_server: { ...config.napcat_server, token: e.target.value },
                })
              }
              placeholder="留空表示无需令牌"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">Napcat 设定的访问令牌，若无则留空</p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="napcat-heartbeat" className="text-sm md:text-base">
              心跳间隔（秒）
            </Label>
            <Input
              id="napcat-heartbeat"
              type="number"
              value={config.napcat_server.heartbeat_interval || ''}
              onChange={(e) =>
                onChange({
                  ...config,
                  napcat_server: {
                    ...config.napcat_server,
                    heartbeat_interval: e.target.value ? parseInt(e.target.value) : 0,
                  },
                })
              }
              placeholder="30"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">
              与 Napcat 设置的心跳间隔保持一致（留空使用默认值 30）
            </p>
          </div>
        </div>
      </div>
    </>
  )
}

// 主程序服务器配置组件
function RiyaBotServerSection({
  config,
  onChange,
}: {
  config: AdapterConfig
  onChange: (config: AdapterConfig) => void
}) {
  return (
    <>
      <MobileSettingsSection title="主程序连接">
        <MobileSettingRow
          htmlFor="riyabot-host-mobile"
          label="主机地址"
          description=".env 中的 HOST 字段"
        >
          <Input
            id="riyabot-host-mobile"
            value={config.maibot_server.host}
            onChange={(e) =>
              onChange({
                ...config,
                maibot_server: { ...config.maibot_server, host: e.target.value },
              })
            }
            placeholder="localhost"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
        <MobileSettingRow
          htmlFor="riyabot-port-mobile"
          label="端口"
          description="留空使用默认值 8000"
        >
          <Input
            id="riyabot-port-mobile"
            type="number"
            value={config.maibot_server.port || ''}
            onChange={(e) =>
              onChange({
                ...config,
                maibot_server: {
                  ...config.maibot_server,
                  port: e.target.value ? parseInt(e.target.value) : 0,
                },
              })
            }
            placeholder="8000"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
        <MobileSettingRow
          htmlFor="riyabot-api-server-mobile"
          label="API-Server 模式"
          description="使用新版 API-Server 地址连接"
        >
          <Switch
            id="riyabot-api-server-mobile"
            checked={config.maibot_server.enable_api_server}
            onCheckedChange={(checked) =>
              onChange({
                ...config,
                maibot_server: { ...config.maibot_server, enable_api_server: checked },
              })
            }
          />
        </MobileSettingRow>
        <MobileSettingRow
          htmlFor="riyabot-base-url-mobile"
          label="API-Server 地址"
          description="仅在 API-Server 模式启用时使用"
        >
          <Input
            id="riyabot-base-url-mobile"
            value={config.maibot_server.base_url}
            onChange={(e) =>
              onChange({
                ...config,
                maibot_server: { ...config.maibot_server, base_url: e.target.value },
              })
            }
            placeholder="ws://127.0.0.1:18095/ws"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
        <MobileSettingRow
          htmlFor="riyabot-api-key-mobile"
          label="API Key"
          description="仅在 API-Server 模式启用时使用"
        >
          <Input
            id="riyabot-api-key-mobile"
            type="password"
            value={config.maibot_server.api_key}
            onChange={(e) =>
              onChange({
                ...config,
                maibot_server: { ...config.maibot_server, api_key: e.target.value },
              })
            }
            placeholder="your-api-key"
            className={MOBILE_SETTING_INPUT_CLASS}
          />
        </MobileSettingRow>
      </MobileSettingsSection>

      <div className="hidden ios-group space-y-4 p-4 md:block md:space-y-6 md:p-6">
        <h3 className="mb-3 text-base font-semibold md:mb-4 md:text-lg">
          主程序 WebSocket 服务设置
        </h3>
        <div className="grid gap-3 md:gap-4">
          <div className="grid gap-2">
            <Label htmlFor="riyabot-host" className="text-sm md:text-base">
              主机地址
            </Label>
            <Input
              id="riyabot-host"
              value={config.maibot_server.host}
              onChange={(e) =>
                onChange({
                  ...config,
                  maibot_server: { ...config.maibot_server, host: e.target.value },
                })
              }
              placeholder="localhost"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">主程序在 .env 文件中设置的 HOST 字段</p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="riyabot-port" className="text-sm md:text-base">
              端口
            </Label>
            <Input
              id="riyabot-port"
              type="number"
              value={config.maibot_server.port || ''}
              onChange={(e) =>
                onChange({
                  ...config,
                  maibot_server: {
                    ...config.maibot_server,
                    port: e.target.value ? parseInt(e.target.value) : 0,
                  },
                })
              }
              placeholder="8000"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">
              主程序在 .env 文件中设置的 PORT 字段（留空使用默认值 8000）
            </p>
          </div>

          <div className="flex items-center justify-between gap-4 rounded-[16px] border border-border/45 bg-muted/35 p-4">
            <div>
              <Label htmlFor="riyabot-api-server" className="text-sm md:text-base">
                API-Server 模式
              </Label>
              <p className="mt-1 text-xs text-muted-foreground">
                启用后通过新版 API-Server 地址连接主程序
              </p>
            </div>
            <Switch
              id="riyabot-api-server"
              checked={config.maibot_server.enable_api_server}
              onCheckedChange={(checked) =>
                onChange({
                  ...config,
                  maibot_server: { ...config.maibot_server, enable_api_server: checked },
                })
              }
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="riyabot-base-url" className="text-sm md:text-base">
              API-Server 地址
            </Label>
            <Input
              id="riyabot-base-url"
              value={config.maibot_server.base_url}
              onChange={(e) =>
                onChange({
                  ...config,
                  maibot_server: { ...config.maibot_server, base_url: e.target.value },
                })
              }
              placeholder="ws://127.0.0.1:18095/ws"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">仅在 API-Server 模式启用时使用</p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="riyabot-api-key" className="text-sm md:text-base">
              API Key
            </Label>
            <Input
              id="riyabot-api-key"
              type="password"
              value={config.maibot_server.api_key}
              onChange={(e) =>
                onChange({
                  ...config,
                  maibot_server: { ...config.maibot_server, api_key: e.target.value },
                })
              }
              placeholder="your-api-key"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">仅在 API-Server 模式启用时使用</p>
          </div>
        </div>
      </div>
    </>
  )
}

// 聊天控制配置组件
function ChatControlSection({
  config,
  onChange,
}: {
  config: AdapterConfig
  onChange: (config: AdapterConfig) => void
}) {
  const addToList = (listType: 'group' | 'private' | 'ban') => {
    const newConfig = { ...config }
    if (listType === 'group') {
      newConfig.chat.group_list = [...newConfig.chat.group_list, 0]
    } else if (listType === 'private') {
      newConfig.chat.private_list = [...newConfig.chat.private_list, 0]
    } else {
      newConfig.chat.ban_user_id = [...newConfig.chat.ban_user_id, 0]
    }
    onChange(newConfig)
  }

  const removeFromList = (listType: 'group' | 'private' | 'ban', index: number) => {
    const newConfig = { ...config }
    if (listType === 'group') {
      newConfig.chat.group_list = newConfig.chat.group_list.filter((_, i) => i !== index)
    } else if (listType === 'private') {
      newConfig.chat.private_list = newConfig.chat.private_list.filter((_, i) => i !== index)
    } else {
      newConfig.chat.ban_user_id = newConfig.chat.ban_user_id.filter((_, i) => i !== index)
    }
    onChange(newConfig)
  }

  const updateListItem = (listType: 'group' | 'private' | 'ban', index: number, value: number) => {
    const newConfig = { ...config }
    if (listType === 'group') {
      newConfig.chat.group_list[index] = value
    } else if (listType === 'private') {
      newConfig.chat.private_list[index] = value
    } else {
      newConfig.chat.ban_user_id[index] = value
    }
    onChange(newConfig)
  }

  return (
    <div className="ios-group space-y-4 p-4 md:space-y-6 md:p-6">
      <div>
        <h3 className="mb-3 text-base font-semibold md:mb-4 md:text-lg">聊天黑白名单功能</h3>
        <div className="grid gap-4 md:gap-6">
          {/* 群组名单 */}
          <div className="space-y-3 md:space-y-4">
            <div className="grid gap-2">
              <Label className="text-sm md:text-base">群组名单类型</Label>
              <Select
                value={config.chat.group_list_type}
                onValueChange={(value: 'whitelist' | 'blacklist') =>
                  onChange({
                    ...config,
                    chat: { ...config.chat, group_list_type: value },
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="whitelist">白名单（仅名单内可聊天）</SelectItem>
                  <SelectItem value="blacklist">黑名单（名单内禁止聊天）</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-0">
                <Label className="text-sm md:text-base">群组列表</Label>
                <Button
                  onClick={() => addToList('group')}
                  size="sm"
                  variant="outline"
                  className="w-full sm:w-auto"
                >
                  <FileText className="mr-1 h-4 w-4" />
                  添加群号
                </Button>
              </div>
              {config.chat.group_list.map((groupId, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    type="number"
                    value={groupId}
                    onChange={(e) => updateListItem('group', index, parseInt(e.target.value) || 0)}
                    placeholder="输入群号"
                    className="text-sm md:text-base"
                  />
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="icon" variant="outline">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>确认删除</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除群号 {groupId} 吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeFromList('group', index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              ))}
              {config.chat.group_list.length === 0 && (
                <p className="text-sm text-muted-foreground">暂无群组</p>
              )}
            </div>
          </div>

          {/* 私聊名单 */}
          <div className="space-y-3 md:space-y-4">
            <div className="grid gap-2">
              <Label className="text-sm md:text-base">私聊名单类型</Label>
              <Select
                value={config.chat.private_list_type}
                onValueChange={(value: 'whitelist' | 'blacklist') =>
                  onChange({
                    ...config,
                    chat: { ...config.chat, private_list_type: value },
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="whitelist">白名单（仅名单内可聊天）</SelectItem>
                  <SelectItem value="blacklist">黑名单（名单内禁止聊天）</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-0">
                <Label className="text-sm md:text-base">私聊列表</Label>
                <Button
                  onClick={() => addToList('private')}
                  size="sm"
                  variant="outline"
                  className="w-full sm:w-auto"
                >
                  <FileText className="mr-1 h-4 w-4" />
                  添加用户
                </Button>
              </div>
              {config.chat.private_list.map((userId, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    type="number"
                    value={userId}
                    onChange={(e) =>
                      updateListItem('private', index, parseInt(e.target.value) || 0)
                    }
                    placeholder="输入QQ号"
                    className="text-sm md:text-base"
                  />
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="icon" variant="outline">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>确认删除</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除用户 {userId} 吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeFromList('private', index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              ))}
              {config.chat.private_list.length === 0 && (
                <p className="text-sm text-muted-foreground">暂无用户</p>
              )}
            </div>
          </div>

          {/* 全局禁止名单 */}
          <div className="space-y-2">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-0">
              <div>
                <Label className="text-sm md:text-base">全局禁止名单</Label>
                <p className="mt-1 text-xs text-muted-foreground">名单中的用户无法进行任何聊天</p>
              </div>
              <Button
                onClick={() => addToList('ban')}
                size="sm"
                variant="outline"
                className="w-full sm:w-auto"
              >
                <FileText className="mr-1 h-4 w-4" />
                添加用户
              </Button>
            </div>
            {config.chat.ban_user_id.map((userId, index) => (
              <div key={index} className="flex gap-2">
                <Input
                  type="number"
                  value={userId}
                  onChange={(e) => updateListItem('ban', index, parseInt(e.target.value) || 0)}
                  placeholder="输入QQ号"
                  className="text-sm md:text-base"
                />
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button size="icon" variant="outline">
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>确认删除</AlertDialogTitle>
                      <AlertDialogDescription>
                        确定要从全局禁止名单中删除用户 {userId} 吗？此操作无法撤销。
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction onClick={() => removeFromList('ban', index)}>
                        删除
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ))}
            {config.chat.ban_user_id.length === 0 && (
              <p className="text-sm text-muted-foreground">暂无禁止用户</p>
            )}
          </div>

          {/* 其他设置 */}
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm md:text-base">屏蔽QQ官方机器人</Label>
              <p className="mt-1 text-xs text-muted-foreground">是否屏蔽来自QQ官方机器人的消息</p>
            </div>
            <Switch
              checked={config.chat.ban_qq_bot}
              onCheckedChange={(checked) =>
                onChange({
                  ...config,
                  chat: { ...config.chat, ban_qq_bot: checked },
                })
              }
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm md:text-base">启用戳一戳功能</Label>
              <p className="mt-1 text-xs text-muted-foreground">是否响应戳一戳消息</p>
            </div>
            <Switch
              checked={config.chat.enable_poke}
              onCheckedChange={(checked) =>
                onChange({
                  ...config,
                  chat: { ...config.chat, enable_poke: checked },
                })
              }
            />
          </div>
        </div>
      </div>
    </div>
  )
}

// 语音配置组件
function VoiceSection({
  config,
  onChange,
}: {
  config: AdapterConfig
  onChange: (config: AdapterConfig) => void
}) {
  return (
    <div className="ios-group space-y-4 p-4 md:space-y-6 md:p-6">
      <div>
        <h3 className="mb-3 text-base font-semibold md:mb-4 md:text-lg">发送语音设置</h3>
        <div className="flex items-center justify-between">
          <div>
            <Label className="text-sm md:text-base">使用 TTS 语音</Label>
            <p className="mt-1 text-xs text-muted-foreground">请确保已配置 TTS 并有对应的适配器</p>
          </div>
          <Switch
            checked={config.voice.use_tts}
            onCheckedChange={(checked) =>
              onChange({
                ...config,
                voice: { use_tts: checked },
              })
            }
          />
        </div>
      </div>
    </div>
  )
}

// 转发消息配置组件
function ForwardSection({
  config,
  onChange,
}: {
  config: AdapterConfig
  onChange: (config: AdapterConfig) => void
}) {
  return (
    <div className="ios-group space-y-4 p-4 md:space-y-6 md:p-6">
      <div>
        <h3 className="mb-3 text-base font-semibold md:mb-4 md:text-lg">转发消息处理设置</h3>
        <div className="grid gap-3 md:gap-4">
          <div className="grid gap-2">
            <Label htmlFor="forward-image-threshold" className="text-sm md:text-base">
              图片数量阈值
            </Label>
            <Input
              id="forward-image-threshold"
              type="number"
              min={0}
              value={config.forward.image_threshold || ''}
              onChange={(e) =>
                onChange({
                  ...config,
                  forward: {
                    ...config.forward,
                    image_threshold: e.target.value ? parseInt(e.target.value) : 0,
                  },
                })
              }
              placeholder="3"
              className="text-sm md:text-base"
            />
            <p className="text-xs text-muted-foreground">
              转发消息中图片数量超过此值时使用占位符，避免 VLM 处理卡死
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

// 调试配置组件
function DebugSection({
  config,
  onChange,
}: {
  config: AdapterConfig
  onChange: (config: AdapterConfig) => void
}) {
  return (
    <div className="ios-group space-y-4 p-4 md:space-y-6 md:p-6">
      <div>
        <h3 className="mb-3 text-base font-semibold md:mb-4 md:text-lg">调试设置</h3>
        <div className="grid gap-3 md:gap-4">
          <div className="grid gap-2">
            <Label className="text-sm md:text-base">日志等级</Label>
            <Select
              value={config.debug.level}
              onValueChange={(value) =>
                onChange({
                  ...config,
                  debug: { level: value },
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="DEBUG">DEBUG（调试）</SelectItem>
                <SelectItem value="INFO">INFO（信息）</SelectItem>
                <SelectItem value="WARNING">WARNING（警告）</SelectItem>
                <SelectItem value="ERROR">ERROR（错误）</SelectItem>
                <SelectItem value="CRITICAL">CRITICAL（严重）</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">设置适配器的日志输出等级</p>
          </div>
        </div>
      </div>
    </div>
  )
}
