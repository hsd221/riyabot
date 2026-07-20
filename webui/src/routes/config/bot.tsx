import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  PersonalitySection,
  ChatSection,
  VoiceSection,
  MessageReceiveSection,
  LogSection,
  DebugSection,
  MaimMessageSection,
  TelemetrySection,
  WebUISection,
  ExperimentalSection,
  FeaturesSection,
  ExpressionSection,
  BehaviorSection,
  ProcessingSection,
} from './bot/sections'
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
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  BrainCircuit,
  Check,
  ChevronRight,
  Filter,
  FlaskConical,
  Layers3,
  MessageCircle,
  Mic2,
  Power,
  Save,
  Server,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  UserRound,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { getBotConfig, updateBotConfig } from '@/lib/config-api'
import { restartRiyaBot } from '@/lib/system-api'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import { RestartingOverlay } from '@/components/RestartingOverlay'

// 导入模块化的类型定义
import type {
  BotConfig,
  PersonalityConfig,
  ChatConfig,
  ExpressionConfig,
  BehaviorConfig,
  EmojiConfig,
  MemoryConfig,
  ToolConfig,
  VoiceConfig,
  MessageReceiveConfig,
  KeywordReactionConfig,
  ResponsePostProcessConfig,
  ChineseTypoConfig,
  ResponseSplitterConfig,
  LogConfig,
  DebugConfig,
  MaimMessageConfig,
  TelemetryConfig,
  WebUIConfig,
  ExperimentalConfig,
  ConfigSectionName,
} from './bot/types'

// 导入 useAutoSave hook
import { useAutoSave, useConfigAutoSave } from './bot/hooks'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'

// ==================== 常量定义 ====================
/** Toast 显示前的延迟时间 (毫秒) */
const TOAST_DISPLAY_DELAY = 500

type LegacyExpressionConfig = Partial<ExpressionConfig> & {
  reflect?: boolean
  reflect_operator_id?: string
}

type BotConfigTab =
  | 'personality'
  | 'chat'
  | 'expression'
  | 'behavior'
  | 'features'
  | 'processing'
  | 'message_receive'
  | 'voice'
  | 'service'
  | 'experimental'
  | 'other'

type ConfigTabItem = {
  value: BotConfigTab
  label: string
  description: string
  Icon: LucideIcon
  color: string
}

const CONFIG_TABS: ConfigTabItem[] = [
  {
    value: 'personality',
    label: '人格',
    description: '特质与表达风格',
    Icon: UserRound,
    color: 'ios-symbol-purple',
  },
  {
    value: 'chat',
    label: '聊天',
    description: '回复频率与上下文',
    Icon: MessageCircle,
    color: 'ios-symbol-green',
  },
  {
    value: 'expression',
    label: '表达',
    description: '表达学习与黑话',
    Icon: Sparkles,
    color: 'ios-symbol-pink',
  },
  {
    value: 'behavior',
    label: '行为',
    description: '行为学习与引用',
    Icon: BrainCircuit,
    color: 'ios-symbol-purple',
  },
  {
    value: 'features',
    label: '功能',
    description: '表情、记忆与工具',
    Icon: Layers3,
    color: 'ios-symbol-purple',
  },
  {
    value: 'processing',
    label: '处理',
    description: '关键词和回复后处理',
    Icon: SlidersHorizontal,
    color: 'ios-symbol-orange',
  },
  {
    value: 'message_receive',
    label: '过滤',
    description: '消息接收规则',
    Icon: Filter,
    color: 'ios-symbol-teal',
  },
  {
    value: 'voice',
    label: '语音',
    description: '语音合成与播放',
    Icon: Mic2,
    color: 'ios-symbol-green',
  },
  {
    value: 'service',
    label: '服务',
    description: 'WebUI 与通信服务',
    Icon: Server,
    color: 'ios-symbol-gray',
  },
  {
    value: 'experimental',
    label: '实验',
    description: '实验性能力开关',
    Icon: FlaskConical,
    color: 'ios-symbol-purple',
  },
  {
    value: 'other',
    label: '其他',
    description: '日志与调试选项',
    Icon: Settings2,
    color: 'ios-symbol-gray',
  },
]

export function BotConfigPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [autoSaving, setAutoSaving] = useState(false)
  const [visualUnsavedChanges, setVisualUnsavedChanges] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [showRestartOverlay, setShowRestartOverlay] = useState(false)
  const [activeTab, setActiveTab] = useState<BotConfigTab>('personality')
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false)
  const { toast } = useToast()
  const activeTabItem = CONFIG_TABS.find((item) => item.value === activeTab) ?? CONFIG_TABS[0]
  const hasUnsavedChanges = visualUnsavedChanges

  // 配置状态
  const [botConfig, setBotConfig] = useState<BotConfig | null>(null)
  const [personalityConfig, setPersonalityConfig] = useState<PersonalityConfig | null>(null)
  const [chatConfig, setChatConfig] = useState<ChatConfig | null>(null)
  const [expressionConfig, setExpressionConfig] = useState<ExpressionConfig | null>(null)
  const [behaviorConfig, setBehaviorConfig] = useState<BehaviorConfig | null>(null)
  const [emojiConfig, setEmojiConfig] = useState<EmojiConfig | null>(null)
  const [memoryConfig, setMemoryConfig] = useState<MemoryConfig | null>(null)
  const [toolConfig, setToolConfig] = useState<ToolConfig | null>(null)
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null)
  const [messageReceiveConfig, setMessageReceiveConfig] = useState<MessageReceiveConfig | null>(
    null
  )
  const [keywordReactionConfig, setKeywordReactionConfig] = useState<KeywordReactionConfig | null>(
    null
  )
  const [responsePostProcessConfig, setResponsePostProcessConfig] =
    useState<ResponsePostProcessConfig | null>(null)
  const [chineseTypoConfig, setChineseTypoConfig] = useState<ChineseTypoConfig | null>(null)
  const [responseSplitterConfig, setResponseSplitterConfig] =
    useState<ResponseSplitterConfig | null>(null)
  const [logConfig, setLogConfig] = useState<LogConfig | null>(null)
  const [debugConfig, setDebugConfig] = useState<DebugConfig | null>(null)
  const [maimMessageConfig, setMaimMessageConfig] = useState<MaimMessageConfig | null>(null)
  const [telemetryConfig, setTelemetryConfig] = useState<TelemetryConfig | null>(null)
  const [webuiConfig, setWebuiConfig] = useState<WebUIConfig | null>(null)
  const [experimentalConfig, setExperimentalConfig] = useState<ExperimentalConfig | null>(null)

  // 用于标记初始加载和配置缓存
  const initialLoadRef = useRef(true)
  const configRef = useRef<Record<string, unknown>>({})

  // ==================== 辅助函数 ====================

  /**
   * 解析并设置所有配置状态
   * 抽取自 loadConfig 中的重复逻辑
   */
  const parseAndSetConfig = useCallback((config: Record<string, unknown>) => {
    configRef.current = config

    setBotConfig(config.bot as BotConfig)

    const personality = (config.personality ?? {}) as Partial<PersonalityConfig>
    setPersonalityConfig({
      personality: personality.personality ?? '',
      reply_style: personality.reply_style ?? '',
    })

    const chat = (config.chat ?? {}) as Partial<ChatConfig>
    setChatConfig({
      talk_value: chat.talk_value ?? 1,
      mentioned_bot_reply: chat.mentioned_bot_reply ?? true,
      at_bot_inevitable_reply: chat.at_bot_inevitable_reply ?? 1,
      max_context_size: chat.max_context_size ?? 18,
      planner_smooth: chat.planner_smooth ?? 3,
      enable_talk_value_rules: chat.enable_talk_value_rules ?? true,
      talk_value_rules: chat.talk_value_rules ?? [],
      plan_reply_log_max_per_chat: chat.plan_reply_log_max_per_chat ?? 1024,
      llm_quote: chat.llm_quote ?? false,
    })

    const expression = (config.expression ?? {}) as LegacyExpressionConfig
    setExpressionConfig({
      learning_list: expression.learning_list ?? [],
      expression_groups: expression.expression_groups ?? [],
      expression_self_reflect: expression.expression_self_reflect ?? false,
      expression_manual_reflect:
        expression.expression_manual_reflect ?? expression.reflect ?? false,
      manual_reflect_operator_id:
        expression.manual_reflect_operator_id ?? expression.reflect_operator_id ?? '',
      allow_reflect: expression.allow_reflect ?? [],
      all_global_jargon: expression.all_global_jargon ?? false,
      enable_jargon_explanation: expression.enable_jargon_explanation ?? true,
      jargon_mode: expression.jargon_mode ?? 'context',
      expression_checked_only: expression.expression_checked_only ?? false,
      expression_auto_check_interval: expression.expression_auto_check_interval ?? 3600,
      expression_auto_check_count: expression.expression_auto_check_count ?? 10,
      expression_auto_check_custom_criteria: expression.expression_auto_check_custom_criteria ?? [],
    })

    const behavior = (config.behavior ?? {}) as Partial<BehaviorConfig>
    setBehaviorConfig({
      learning_list: behavior.learning_list ?? [],
      behavior_groups: behavior.behavior_groups ?? [],
    })

    setEmojiConfig(config.emoji as EmojiConfig)

    const memory = (config.memory ?? {}) as Partial<MemoryConfig>
    setMemoryConfig({
      max_agent_iterations: memory.max_agent_iterations ?? 5,
      agent_timeout_seconds: memory.agent_timeout_seconds ?? 120,
      global_memory: memory.global_memory ?? false,
      global_memory_blacklist: memory.global_memory_blacklist ?? [],
      planner_question: memory.planner_question ?? true,
      sqlite_path: memory.sqlite_path ?? 'data/memory.db',
      qdrant_url: memory.qdrant_url ?? '',
      qdrant_api_key: memory.qdrant_api_key ?? '',
      qdrant_local_path: memory.qdrant_local_path ?? 'data/qdrant',
      embedding_dimension: memory.embedding_dimension ?? 1024,
      collection_name_atoms: memory.collection_name_atoms ?? 'memory_atoms',
      collection_name_graph: memory.collection_name_graph ?? 'graph_entries',
      vector_batch_size: memory.vector_batch_size ?? 100,
    })

    setToolConfig(config.tool as ToolConfig)
    setVoiceConfig(config.voice as VoiceConfig)
    const messageReceive = (config.message_receive ?? {}) as Partial<MessageReceiveConfig>
    setMessageReceiveConfig({
      ban_words: messageReceive.ban_words ?? [],
      ban_msgs_regex: messageReceive.ban_msgs_regex ?? [],
    })
    setKeywordReactionConfig(config.keyword_reaction as KeywordReactionConfig)
    setResponsePostProcessConfig(config.response_post_process as ResponsePostProcessConfig)
    setChineseTypoConfig(config.chinese_typo as ChineseTypoConfig)
    setResponseSplitterConfig(config.response_splitter as ResponseSplitterConfig)

    const log = (config.log ?? {}) as Partial<LogConfig>
    setLogConfig({
      date_style: log.date_style ?? 'm-d H:i:s',
      log_level_style: log.log_level_style === 'FULL' ? 'full' : (log.log_level_style ?? 'lite'),
      color_text: log.color_text ?? 'full',
      log_level: log.log_level ?? 'INFO',
      console_log_level: log.console_log_level ?? 'INFO',
      file_log_level: log.file_log_level ?? 'DEBUG',
      suppress_libraries: log.suppress_libraries ?? [],
      library_log_levels: log.library_log_levels ?? {},
    })

    const debug = (config.debug ?? {}) as Partial<DebugConfig>
    setDebugConfig({
      show_prompt: debug.show_prompt ?? false,
      show_replyer_prompt: debug.show_replyer_prompt ?? true,
      show_replyer_reasoning: debug.show_replyer_reasoning ?? true,
      show_jargon_prompt: debug.show_jargon_prompt ?? false,
      show_memory_prompt: debug.show_memory_prompt ?? false,
      show_planner_prompt: debug.show_planner_prompt ?? false,
      show_lpmm_paragraph: debug.show_lpmm_paragraph ?? false,
    })

    const maimMessage = (config.maim_message ?? {}) as Partial<MaimMessageConfig>
    setMaimMessageConfig({
      auth_token: maimMessage.auth_token ?? [],
      enable_api_server: maimMessage.enable_api_server ?? false,
      api_server_host: maimMessage.api_server_host ?? '0.0.0.0',
      api_server_port: maimMessage.api_server_port ?? 8090,
      api_server_use_wss: maimMessage.api_server_use_wss ?? false,
      api_server_cert_file: maimMessage.api_server_cert_file ?? '',
      api_server_key_file: maimMessage.api_server_key_file ?? '',
      api_server_allowed_api_keys: maimMessage.api_server_allowed_api_keys ?? [],
    })

    setTelemetryConfig(config.telemetry as TelemetryConfig)

    const webui = (config.webui ?? {}) as Partial<WebUIConfig>
    setWebuiConfig({
      enabled: webui.enabled ?? true,
      mode: webui.mode ?? 'production',
      anti_crawler_mode: webui.anti_crawler_mode ?? 'basic',
      allowed_ips: webui.allowed_ips ?? '127.0.0.1',
      trusted_proxies: webui.trusted_proxies ?? '',
      trust_xff: webui.trust_xff ?? false,
      secure_cookie: webui.secure_cookie ?? false,
    })

    const experimental = (config.experimental ?? {}) as Partial<ExperimentalConfig>
    setExperimentalConfig({
      chat_prompts: experimental.chat_prompts ?? [],
    })
  }, [])

  /**
   * 构建完整的配置对象用于保存
   * 抽取自 saveConfig 和 handleSaveAndRestart 中的重复逻辑
   */
  const buildFullConfig = useCallback(() => {
    return {
      ...configRef.current,
      bot: botConfig,
      personality: personalityConfig,
      chat: chatConfig,
      expression: expressionConfig,
      behavior: behaviorConfig,
      emoji: emojiConfig,
      memory: memoryConfig,
      tool: toolConfig,
      voice: voiceConfig,
      message_receive: messageReceiveConfig,
      keyword_reaction: keywordReactionConfig,
      response_post_process: responsePostProcessConfig,
      chinese_typo: chineseTypoConfig,
      response_splitter: responseSplitterConfig,
      log: logConfig,
      debug: debugConfig,
      maim_message: maimMessageConfig,
      telemetry: telemetryConfig,
      webui: webuiConfig,
      experimental: experimentalConfig,
    }
  }, [
    botConfig,
    personalityConfig,
    chatConfig,
    expressionConfig,
    behaviorConfig,
    emojiConfig,
    memoryConfig,
    toolConfig,
    voiceConfig,
    messageReceiveConfig,
    keywordReactionConfig,
    responsePostProcessConfig,
    chineseTypoConfig,
    responseSplitterConfig,
    logConfig,
    debugConfig,
    maimMessageConfig,
    telemetryConfig,
    webuiConfig,
    experimentalConfig,
  ])

  // 加载配置
  const loadConfig = useCallback(async () => {
    try {
      setLoading(true)
      const config = await getBotConfig()
      parseAndSetConfig(config)
      setVisualUnsavedChanges(false)
      initialLoadRef.current = false
    } catch (error) {
      console.error('加载配置失败:', error)
      toast({
        title: '加载失败',
        description: '无法加载配置文件',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [toast, parseAndSetConfig])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  // 使用模块化的 useAutoSave hook
  const { triggerAutoSave, cancelPendingAutoSave } = useAutoSave(
    initialLoadRef.current,
    setAutoSaving,
    setVisualUnsavedChanges
  )

  const triggerVisualAutoSave = useCallback(
    (sectionName: ConfigSectionName, sectionData: unknown) => {
      triggerAutoSave(sectionName, sectionData)
    },
    [triggerAutoSave]
  )

  // 使用 useConfigAutoSave hook 简化配置变化监听
  // 注意: useConfigAutoSave 是一个 hook，不能在条件语句或循环中调用
  // 因此我们仍然需要逐个调用，但代码更简洁
  useConfigAutoSave(botConfig, 'bot', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(personalityConfig, 'personality', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(chatConfig, 'chat', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(expressionConfig, 'expression', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(behaviorConfig, 'behavior', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(emojiConfig, 'emoji', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(memoryConfig, 'memory', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(toolConfig, 'tool', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(voiceConfig, 'voice', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(
    messageReceiveConfig,
    'message_receive',
    initialLoadRef.current,
    triggerVisualAutoSave
  )
  useConfigAutoSave(
    keywordReactionConfig,
    'keyword_reaction',
    initialLoadRef.current,
    triggerVisualAutoSave
  )
  useConfigAutoSave(
    responsePostProcessConfig,
    'response_post_process',
    initialLoadRef.current,
    triggerVisualAutoSave
  )
  useConfigAutoSave(
    chineseTypoConfig,
    'chinese_typo',
    initialLoadRef.current,
    triggerVisualAutoSave
  )
  useConfigAutoSave(
    responseSplitterConfig,
    'response_splitter',
    initialLoadRef.current,
    triggerVisualAutoSave
  )
  useConfigAutoSave(logConfig, 'log', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(debugConfig, 'debug', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(
    maimMessageConfig,
    'maim_message',
    initialLoadRef.current,
    triggerVisualAutoSave
  )
  useConfigAutoSave(telemetryConfig, 'telemetry', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(webuiConfig, 'webui', initialLoadRef.current, triggerVisualAutoSave)
  useConfigAutoSave(
    experimentalConfig,
    'experimental',
    initialLoadRef.current,
    triggerVisualAutoSave
  )

  // 手动保存
  const saveConfig = async () => {
    try {
      setSaving(true)
      // 取消待处理的自动保存
      cancelPendingAutoSave()

      await updateBotConfig(buildFullConfig())
      setVisualUnsavedChanges(false)
      toast({
        title: '保存成功',
        description: '主程序配置已保存',
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
      // 取消待处理的自动保存
      cancelPendingAutoSave()

      await updateBotConfig(buildFullConfig())
      setVisualUnsavedChanges(false)
      toast({
        title: '保存成功',
        description: '配置已保存，即将重启主程序...',
      })
      // 等待一下让用户看到保存成功的提示
      await new Promise((resolve) => setTimeout(resolve, TOAST_DISPLAY_DELAY))
      await handleRestart()
    } catch (error) {
      console.error('保存失败:', error)
      toast({
        title: '保存失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
    } finally {
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
      title: '重启失败',
      description: '服务器未能在预期时间内恢复，请手动检查',
      variant: 'destructive',
    })
  }

  if (loading) {
    return (
      <ScrollArea className="h-full">
        <div className="ios-page">
          <div className="ios-card flex h-64 items-center justify-center">
            <p className="text-muted-foreground">加载中...</p>
          </div>
        </div>
      </ScrollArea>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="ios-page space-y-5 sm:space-y-6">
        {/* 页面标题 */}
        <div className="flex flex-col gap-3 sm:gap-4">
          <div className="flex flex-row items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="ios-title">主程序配置</h1>
              <p className="ios-subtitle hidden sm:block">管理当前实例的核心功能和行为设置</p>
            </div>
            {/* 按钮组 - 桌面端靠右 */}
            <div className="hidden flex-shrink-0 gap-2 sm:flex">
              <Button
                onClick={saveConfig}
                disabled={saving || autoSaving || !hasUnsavedChanges || restarting}
                size="sm"
                variant="outline"
                className="h-11 w-11 px-0 sm:w-auto sm:min-w-24 sm:px-4"
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
                <Save className="h-4 w-4 flex-shrink-0 sm:mr-2" strokeWidth={2} fill="none" />
                <span className="hidden sm:inline">
                  {saving ? '保存中' : autoSaving ? '自动' : hasUnsavedChanges ? '保存' : '已保存'}
                </span>
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    disabled={saving || autoSaving || restarting}
                    size="sm"
                    className="h-11 w-11 px-0 sm:w-auto sm:min-w-28 sm:px-4"
                    aria-label={
                      restarting ? '重启中' : hasUnsavedChanges ? '保存并重启' : '重启主程序'
                    }
                    title={
                      restarting ? '重启中...' : hasUnsavedChanges ? '保存并重启' : '重启主程序'
                    }
                  >
                    <Power className="h-4 w-4 flex-shrink-0 sm:mr-2" />
                    <span className="hidden sm:inline">
                      {restarting ? '重启中' : hasUnsavedChanges ? '保存并重启' : '重启主程序'}
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
        </div>

        <div className="ios-group overflow-hidden sm:hidden">
          <div className="ios-row min-h-[66px] gap-3 py-3">
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                <Save className="h-4 w-4" />
              </span>
              <span className="min-w-0">
                <span className="block text-[16px] font-medium leading-6">配置状态</span>
                <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                  {saving
                    ? '正在写入配置'
                    : autoSaving
                      ? '自动保存中'
                      : hasUnsavedChanges
                        ? '有更改等待写入'
                        : '当前配置已保存'}
                </span>
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              {hasUnsavedChanges || saving || autoSaving ? (
                <button
                  type="button"
                  onClick={saveConfig}
                  disabled={saving || autoSaving || !hasUnsavedChanges || restarting}
                  className="ios-touch inline-flex h-11 min-w-[64px] items-center justify-center rounded-full bg-primary px-4 text-[15px] font-semibold leading-none text-primary-foreground shadow-[0_8px_18px_hsl(var(--primary)_/_0.22)] disabled:bg-secondary disabled:text-muted-foreground disabled:shadow-none disabled:active:scale-100"
                >
                  {saving ? '保存中' : autoSaving ? '自动' : '保存'}
                </button>
              ) : (
                <span className="inline-flex h-11 min-w-[72px] items-center justify-center gap-1.5 rounded-full bg-secondary/80 px-3 text-[15px] font-medium leading-none text-muted-foreground">
                  <Check className="h-4 w-4" strokeWidth={2.5} />
                  已保存
                </span>
              )}

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <button
                    type="button"
                    disabled={saving || autoSaving || restarting}
                    className="ios-touch inline-flex h-11 min-w-[70px] items-center justify-center gap-1.5 rounded-full bg-secondary/85 px-3 text-[15px] font-semibold leading-none text-foreground hover:bg-secondary disabled:opacity-50 disabled:active:scale-100"
                    aria-label={
                      restarting ? '重启中' : hasUnsavedChanges ? '保存并重启' : '重启主程序'
                    }
                  >
                    <Power className="h-4 w-4" strokeWidth={2.4} />
                    <span>{restarting ? '重启中' : '重启'}</span>
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
            </span>
          </div>
        </div>

        <Dialog open={categoryDialogOpen} onOpenChange={setCategoryDialogOpen}>
          <DialogTrigger asChild>
            <button
              type="button"
              className="ios-group ios-touch flex w-full items-center justify-between gap-4 px-4 py-3 text-left sm:hidden"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className={cn('ios-symbol ios-symbol-sm', activeTabItem.color)}>
                  <activeTabItem.Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[15px] font-medium leading-5 text-foreground">
                    当前分类
                  </span>
                  <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                    {activeTabItem.label} · {activeTabItem.description}
                  </span>
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </button>
          </DialogTrigger>
          <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
            <DialogHeader className="px-5 pb-1 pt-5">
              <DialogTitle>配置分类</DialogTitle>
              <DialogDescription>选择要编辑的主程序配置</DialogDescription>
            </DialogHeader>
            <div className="ios-scrollbar-none max-h-[min(64vh,560px)] overflow-y-auto px-5 pb-5">
              <div className="ios-group overflow-hidden">
                {CONFIG_TABS.map((item) => {
                  const selected = item.value === activeTab
                  return (
                    <button
                      key={item.value}
                      type="button"
                      className="ios-touch flex min-h-[62px] w-full items-center justify-between gap-3 border-b border-border/70 px-4 py-3 text-left last:border-b-0 hover:bg-accent/55"
                      aria-current={selected ? 'page' : undefined}
                      onClick={() => {
                        setActiveTab(item.value)
                        setCategoryDialogOpen(false)
                      }}
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span className={cn('ios-symbol ios-symbol-sm', item.color)}>
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
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as BotConfigTab)}
          className="w-full space-y-1"
        >
          <TabsList className="hidden h-auto w-fit max-w-full flex-wrap justify-start gap-1 rounded-[16px] p-1 sm:inline-flex">
            <TabsTrigger value="personality" className="min-w-[4.5rem] px-3 py-2 text-xs">
              人格
            </TabsTrigger>
            <TabsTrigger value="chat" className="min-w-[4.5rem] px-3 py-2 text-xs">
              聊天
            </TabsTrigger>
            <TabsTrigger value="expression" className="min-w-[4.5rem] px-3 py-2 text-xs">
              表达
            </TabsTrigger>
            <TabsTrigger value="behavior" className="min-w-[4.5rem] px-3 py-2 text-xs">
              行为
            </TabsTrigger>
            <TabsTrigger value="features" className="min-w-[4.5rem] px-3 py-2 text-xs">
              功能
            </TabsTrigger>
            <TabsTrigger value="processing" className="min-w-[4.5rem] px-3 py-2 text-xs">
              处理
            </TabsTrigger>
            <TabsTrigger value="message_receive" className="min-w-[4.5rem] px-3 py-2 text-xs">
              过滤
            </TabsTrigger>
            <TabsTrigger value="voice" className="min-w-[4.5rem] px-3 py-2 text-xs">
              语音
            </TabsTrigger>
            <TabsTrigger value="service" className="min-w-[4.5rem] px-3 py-2 text-xs">
              服务
            </TabsTrigger>
            <TabsTrigger value="experimental" className="min-w-[4.5rem] px-3 py-2 text-xs">
              实验
            </TabsTrigger>
            <TabsTrigger value="other" className="min-w-[4.5rem] px-3 py-2 text-xs">
              其他
            </TabsTrigger>
          </TabsList>
          {/* 人格配置 */}
          <TabsContent value="personality" className="mt-5 space-y-5 sm:mt-6">
            {personalityConfig && (
              <PersonalitySection config={personalityConfig} onChange={setPersonalityConfig} />
            )}
          </TabsContent>

          {/* 聊天配置 */}
          <TabsContent value="chat" className="mt-5 space-y-5 sm:mt-6">
            {chatConfig && <ChatSection config={chatConfig} onChange={setChatConfig} />}
          </TabsContent>

          {/* 表达配置 */}
          <TabsContent value="expression" className="mt-5 space-y-5 sm:mt-6">
            {expressionConfig && (
              <ExpressionSection config={expressionConfig} onChange={setExpressionConfig} />
            )}
          </TabsContent>

          {/* 行为学习配置 */}
          <TabsContent value="behavior" className="mt-5 space-y-5 sm:mt-6">
            {behaviorConfig && (
              <BehaviorSection config={behaviorConfig} onChange={setBehaviorConfig} />
            )}
          </TabsContent>

          {/* 功能配置（合并表情、记忆、工具） */}
          <TabsContent value="features" className="mt-5 space-y-5 sm:mt-6">
            {emojiConfig && memoryConfig && toolConfig && (
              <FeaturesSection
                emojiConfig={emojiConfig}
                memoryConfig={memoryConfig}
                toolConfig={toolConfig}
                onEmojiChange={setEmojiConfig}
                onMemoryChange={setMemoryConfig}
                onToolChange={setToolConfig}
              />
            )}
          </TabsContent>

          {/* 处理配置（关键词反应和回复后处理） */}
          <TabsContent value="processing" className="mt-5 space-y-5 sm:mt-6">
            {keywordReactionConfig &&
              responsePostProcessConfig &&
              chineseTypoConfig &&
              responseSplitterConfig && (
                <ProcessingSection
                  keywordReactionConfig={keywordReactionConfig}
                  responsePostProcessConfig={responsePostProcessConfig}
                  chineseTypoConfig={chineseTypoConfig}
                  responseSplitterConfig={responseSplitterConfig}
                  onKeywordReactionChange={setKeywordReactionConfig}
                  onResponsePostProcessChange={setResponsePostProcessConfig}
                  onChineseTypoChange={setChineseTypoConfig}
                  onResponseSplitterChange={setResponseSplitterConfig}
                />
              )}
          </TabsContent>

          {/* 语音配置 */}
          <TabsContent value="voice" className="mt-5 space-y-5 sm:mt-6">
            {voiceConfig && <VoiceSection config={voiceConfig} onChange={setVoiceConfig} />}
          </TabsContent>

          {/* 消息过滤配置 */}
          <TabsContent value="message_receive" className="mt-5 space-y-5 sm:mt-6">
            {messageReceiveConfig && (
              <MessageReceiveSection
                config={messageReceiveConfig}
                onChange={setMessageReceiveConfig}
              />
            )}
          </TabsContent>

          {/* 服务配置 */}
          <TabsContent value="service" className="mt-5 space-y-5 sm:mt-6">
            {webuiConfig && <WebUISection config={webuiConfig} onChange={setWebuiConfig} />}
            {maimMessageConfig && (
              <MaimMessageSection config={maimMessageConfig} onChange={setMaimMessageConfig} />
            )}
            {telemetryConfig && (
              <TelemetrySection config={telemetryConfig} onChange={setTelemetryConfig} />
            )}
          </TabsContent>

          {/* 实验配置 */}
          <TabsContent value="experimental" className="mt-5 space-y-5 sm:mt-6">
            {experimentalConfig && (
              <ExperimentalSection config={experimentalConfig} onChange={setExperimentalConfig} />
            )}
          </TabsContent>

          {/* 其他配置 */}
          <TabsContent value="other" className="mt-5 space-y-5 sm:mt-6">
            {logConfig && <LogSection config={logConfig} onChange={setLogConfig} />}
            {debugConfig && <DebugSection config={debugConfig} onChange={setDebugConfig} />}
          </TabsContent>
        </Tabs>

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
