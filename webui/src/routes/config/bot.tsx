import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  BotInfoSection,
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
  DreamSection,
  FeaturesSection,
  ExpressionSection,
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
import { ScrollArea } from '@/components/ui/scroll-area'
import { Save, Power, Code2, Layout } from 'lucide-react'
import { getBotConfig, updateBotConfig, getBotConfigRaw, updateBotConfigRaw } from '@/lib/config-api'
import { restartRiyaBot } from '@/lib/system-api'
import { useToast } from '@/hooks/use-toast'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Info } from 'lucide-react'
import { RestartingOverlay } from '@/components/RestartingOverlay'
import { CodeEditor } from '@/components'

// 导入模块化的类型定义
import type {
  BotConfig,
  PersonalityConfig,
  ChatConfig,
  ExpressionConfig,
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
  DreamConfig,
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

export function BotConfigPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [autoSaving, setAutoSaving] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [showRestartOverlay, setShowRestartOverlay] = useState(false)
  const [editMode, setEditMode] = useState<'visual' | 'source'>('visual')
  const [sourceCode, setSourceCode] = useState<string>('')
  const [hasTomlError, setHasTomlError] = useState(false)
  const { toast } = useToast()

  // 配置状态
  const [botConfig, setBotConfig] = useState<BotConfig | null>(null)
  const [personalityConfig, setPersonalityConfig] = useState<PersonalityConfig | null>(null)
  const [chatConfig, setChatConfig] = useState<ChatConfig | null>(null)
  const [expressionConfig, setExpressionConfig] = useState<ExpressionConfig | null>(null)
  const [emojiConfig, setEmojiConfig] = useState<EmojiConfig | null>(null)
  const [memoryConfig, setMemoryConfig] = useState<MemoryConfig | null>(null)
  const [toolConfig, setToolConfig] = useState<ToolConfig | null>(null)
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null)
  const [messageReceiveConfig, setMessageReceiveConfig] = useState<MessageReceiveConfig | null>(null)
  const [keywordReactionConfig, setKeywordReactionConfig] = useState<KeywordReactionConfig | null>(null)
  const [responsePostProcessConfig, setResponsePostProcessConfig] = useState<ResponsePostProcessConfig | null>(null)
  const [chineseTypoConfig, setChineseTypoConfig] = useState<ChineseTypoConfig | null>(null)
  const [responseSplitterConfig, setResponseSplitterConfig] = useState<ResponseSplitterConfig | null>(null)
  const [logConfig, setLogConfig] = useState<LogConfig | null>(null)
  const [debugConfig, setDebugConfig] = useState<DebugConfig | null>(null)
  const [maimMessageConfig, setMaimMessageConfig] = useState<MaimMessageConfig | null>(null)
  const [telemetryConfig, setTelemetryConfig] = useState<TelemetryConfig | null>(null)
  const [webuiConfig, setWebuiConfig] = useState<WebUIConfig | null>(null)
  const [experimentalConfig, setExperimentalConfig] = useState<ExperimentalConfig | null>(null)
  const [dreamConfig, setDreamConfig] = useState<DreamConfig | null>(null)

  // 用于标记初始加载和配置缓存
  const initialLoadRef = useRef(true)
  const configRef = useRef<Record<string, unknown>>({})

  // ==================== 辅助函数 ====================
  
  /**
   * 解析并设置所有配置状态
   * 抽取自 loadConfig 和 handleModeChange 中的重复逻辑
   */
  const parseAndSetConfig = useCallback((config: Record<string, unknown>) => {
    configRef.current = config

    setBotConfig(config.bot as BotConfig)

    const personality = (config.personality ?? {}) as Partial<PersonalityConfig>
    setPersonalityConfig({
      personality: personality.personality ?? '',
      reply_style: personality.reply_style ?? '',
      multiple_reply_style: personality.multiple_reply_style ?? [],
      multiple_probability: personality.multiple_probability ?? 0,
      plan_style: personality.plan_style ?? '',
      visual_style: personality.visual_style ?? '',
      states: personality.states ?? [],
      state_probability: personality.state_probability ?? 0,
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
      expression_manual_reflect: expression.expression_manual_reflect ?? expression.reflect ?? false,
      manual_reflect_operator_id: expression.manual_reflect_operator_id ?? expression.reflect_operator_id ?? '',
      allow_reflect: expression.allow_reflect ?? [],
      all_global_jargon: expression.all_global_jargon ?? false,
      enable_jargon_explanation: expression.enable_jargon_explanation ?? true,
      jargon_mode: expression.jargon_mode ?? 'context',
      expression_checked_only: expression.expression_checked_only ?? false,
      expression_auto_check_interval: expression.expression_auto_check_interval ?? 3600,
      expression_auto_check_count: expression.expression_auto_check_count ?? 10,
      expression_auto_check_custom_criteria: expression.expression_auto_check_custom_criteria ?? [],
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
      log_level_style: log.log_level_style === 'FULL' ? 'full' : log.log_level_style ?? 'lite',
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
    const legacyPersonality = (config.personality ?? {}) as Partial<ExperimentalConfig>
    setExperimentalConfig({
      private_plan_style: experimental.private_plan_style ?? legacyPersonality.private_plan_style ?? '',
      chat_prompts: experimental.chat_prompts ?? [],
    })

    const dream = (config.dream ?? {}) as Partial<DreamConfig>
    setDreamConfig({
      interval_minutes: dream.interval_minutes ?? 30,
      max_iterations: dream.max_iterations ?? 20,
      first_delay_seconds: dream.first_delay_seconds ?? 60,
      dream_send: dream.dream_send ?? '',
      dream_time_ranges: dream.dream_time_ranges ?? [],
      dream_visible: dream.dream_visible ?? false,
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
      dream: dreamConfig,
    }
  }, [
    botConfig, personalityConfig, chatConfig, expressionConfig,
    emojiConfig, memoryConfig, toolConfig,
    voiceConfig, messageReceiveConfig, keywordReactionConfig, responsePostProcessConfig,
    chineseTypoConfig, responseSplitterConfig, logConfig, debugConfig,
    maimMessageConfig, telemetryConfig, webuiConfig, experimentalConfig, dreamConfig
  ])

  // 加载源代码
  const loadSourceCode = useCallback(async () => {
    try {
      const raw = await getBotConfigRaw()
      setSourceCode(raw)
      setHasTomlError(false)
    } catch (error) {
      toast({
        variant: 'destructive',
        title: '加载失败',
        description: error instanceof Error ? error.message : '加载源代码失败',
      })
    }
  }, [toast])

  // 加载配置
  const loadConfig = useCallback(async () => {
    try {
      setLoading(true)
      const config = await getBotConfig()
      parseAndSetConfig(config)
      setHasUnsavedChanges(false)
      initialLoadRef.current = false
      
      // 同时加载源代码
      await loadSourceCode()
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
  }, [toast, loadSourceCode, parseAndSetConfig])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  // 使用模块化的 useAutoSave hook
  const { triggerAutoSave, cancelPendingAutoSave } = useAutoSave(
    initialLoadRef.current,
    setAutoSaving,
    setHasUnsavedChanges
  )

  // 使用 useConfigAutoSave hook 简化配置变化监听
  // 注意: useConfigAutoSave 是一个 hook，不能在条件语句或循环中调用
  // 因此我们仍然需要逐个调用，但代码更简洁
  useConfigAutoSave(botConfig, 'bot', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(personalityConfig, 'personality', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(chatConfig, 'chat', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(expressionConfig, 'expression', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(emojiConfig, 'emoji', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(memoryConfig, 'memory', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(toolConfig, 'tool', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(voiceConfig, 'voice', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(messageReceiveConfig, 'message_receive', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(keywordReactionConfig, 'keyword_reaction', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(responsePostProcessConfig, 'response_post_process', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(chineseTypoConfig, 'chinese_typo', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(responseSplitterConfig, 'response_splitter', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(logConfig, 'log', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(debugConfig, 'debug', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(maimMessageConfig, 'maim_message', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(telemetryConfig, 'telemetry', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(webuiConfig, 'webui', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(experimentalConfig, 'experimental', initialLoadRef.current, triggerAutoSave)
  useConfigAutoSave(dreamConfig, 'dream', initialLoadRef.current, triggerAutoSave)

  // 保存源代码
  const saveSourceCode = async () => {
    try {
      setSaving(true)
      await updateBotConfigRaw(sourceCode)
      setHasUnsavedChanges(false)
      setHasTomlError(false)
      toast({
        title: '保存成功',
        description: '配置已保存',
      })
      // 重新加载可视化配置
      await loadConfig()
    } catch (error) {
      setHasTomlError(true)
      toast({
        variant: 'destructive',
        title: '保存失败',
        description: error instanceof Error ? error.message : '保存配置失败',
      })
    } finally {
      setSaving(false)
    }
  }

  // 处理模式切换
  const handleModeChange = async (mode: 'visual' | 'source') => {
    if (hasUnsavedChanges) {
      toast({
        variant: 'destructive',
        title: '切换失败',
        description: '请先保存当前更改',
      })
      return
    }

    setEditMode(mode)
    if (mode === 'source') {
      await loadSourceCode()
    } else {
      // 切换回可视化时,直接重新加载配置但不显示全局 loading
      try {
        const config = await getBotConfig()
        parseAndSetConfig(config)
        setHasUnsavedChanges(false)
      } catch (error) {
        console.error('加载配置失败:', error)
        toast({
          title: '加载失败',
          description: '无法加载配置文件',
          variant: 'destructive',
        })
      }
    }
  }

  // 手动保存
  const saveConfig = async () => {
    try {
      setSaving(true)
      // 取消待处理的自动保存
      cancelPendingAutoSave()
      
      await updateBotConfig(buildFullConfig())
      setHasUnsavedChanges(false)
      toast({
        title: '保存成功',
        description: '璃夜主程序配置已保存',
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

  // 重启璃夜
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
      setHasUnsavedChanges(false)
      toast({
        title: '保存成功',
        description: '配置已保存，即将重启璃夜...',
      })
      // 等待一下让用户看到保存成功的提示
      await new Promise(resolve => setTimeout(resolve, TOAST_DISPLAY_DELAY))
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
        <div className="space-y-4 sm:space-y-6 p-4 sm:p-6">
          <div className="flex items-center justify-center h-64">
            <p className="text-muted-foreground">加载中...</p>
          </div>
        </div>
      </ScrollArea>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 sm:space-y-6 p-4 sm:p-6">
        {/* 页面标题 */}
        <div className="flex flex-col gap-3 sm:gap-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-xl sm:text-2xl md:text-3xl font-bold">璃夜主程序配置</h1>
              <p className="text-muted-foreground mt-1 text-xs sm:text-sm">管理璃夜的核心功能和行为设置</p>
            </div>
            {/* 按钮组 - 桌面端靠右 */}
            <div className="flex gap-2 flex-shrink-0">
              <Button
                onClick={editMode === 'visual' ? saveConfig : saveSourceCode}
                disabled={saving || autoSaving || !hasUnsavedChanges || restarting}
                size="sm"
                variant="outline"
                className="w-20 sm:w-24"
              >
                <Save className="h-4 w-4 flex-shrink-0" strokeWidth={2} fill="none" />
                <span className="ml-1 truncate text-xs sm:text-sm">
                  {saving ? '保存中' : autoSaving ? '自动' : hasUnsavedChanges ? '保存' : '已保存'}
                </span>
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    disabled={saving || autoSaving || restarting}
                    size="sm"
                    className="w-20 sm:w-28"
                  >
                    <Power className="h-4 w-4 flex-shrink-0" />
                    <span className="ml-1 truncate text-xs sm:text-sm">
                      {restarting ? '重启中' : hasUnsavedChanges ? '保存重启' : '重启'}
                    </span>
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>确认重启璃夜？</AlertDialogTitle>
                  <AlertDialogDescription asChild>
                    <div>
                      <p>
                        {hasUnsavedChanges 
                          ? '当前有未保存的配置更改。点击确认将先保存配置,然后重启璃夜使新配置生效。重启过程中璃夜将暂时离线。'
                          : '即将重启璃夜主程序。重启过程中璃夜将暂时离线,配置将在重启后生效。'
                        }
                      </p>
                    </div>
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction onClick={hasUnsavedChanges ? handleSaveAndRestart : handleRestart}>
                    {hasUnsavedChanges ? '保存并重启' : '确认重启'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            </div>
          </div>
          
          {/* 模式切换 - 单独一行 */}
          <div className="flex">
            <Tabs value={editMode} onValueChange={(v) => handleModeChange(v as 'visual' | 'source')} className="w-full">
              <TabsList className="h-8 sm:h-9 w-full grid grid-cols-2">
                <TabsTrigger value="visual" className="text-xs sm:text-sm">
                  <Layout className="h-3 w-3 sm:h-4 sm:w-4 mr-1" />
                  可视化编辑
                </TabsTrigger>
                <TabsTrigger value="source" className="text-xs sm:text-sm">
                  <Code2 className="h-3 w-3 sm:h-4 sm:w-4 mr-1" />
                  源代码编辑
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </div>

        {/* 重启提示 */}
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            配置更新后需要<strong>重启璃夜</strong>才能生效。你可以点击右上角的"保存并重启"按钮一键完成保存和重启。
          </AlertDescription>
        </Alert>

        {/* 源代码模式 */}
        {editMode === 'source' && (
          <div className="space-y-4">
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>
                <strong>源代码模式（高级功能）：</strong>直接编辑 TOML 配置文件。此功能仅适用于熟悉 TOML 语法的高级用户。保存时会在后端验证格式，只有格式完全正确才能保存。
                {hasTomlError && (
                  <span className="text-destructive font-semibold ml-2">⚠️ 上次保存失败，请检查 TOML 格式</span>
                )}
              </AlertDescription>
            </Alert>
            
            <CodeEditor
              value={sourceCode}
              onChange={(value) => {
                setSourceCode(value)
                setHasUnsavedChanges(true)
                // 清除之前的错误状态
                if (hasTomlError) {
                  setHasTomlError(false)
                }
              }}
              language="toml"
              theme="dark"
              height="calc(100vh - 280px)"
              minHeight="500px"
              placeholder="TOML 配置内容"
            />
          </div>
        )}

        {/* 可视化模式 */}
        {editMode === 'visual' && (
          <>
        {/* 标签页 */}
        <Tabs defaultValue="bot" className="w-full">
          <TabsList className="flex flex-wrap h-auto gap-1 p-1 sm:grid sm:grid-cols-5 lg:grid-cols-12">
            <TabsTrigger value="bot" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">基本信息</TabsTrigger>
            <TabsTrigger value="personality" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">人格</TabsTrigger>
            <TabsTrigger value="chat" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">聊天</TabsTrigger>
            <TabsTrigger value="expression" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">表达</TabsTrigger>
            <TabsTrigger value="features" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">功能</TabsTrigger>
            <TabsTrigger value="processing" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">处理</TabsTrigger>
            <TabsTrigger value="message_receive" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">过滤</TabsTrigger>
            <TabsTrigger value="voice" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">语音</TabsTrigger>
            <TabsTrigger value="service" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">服务</TabsTrigger>
            <TabsTrigger value="experimental" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">实验</TabsTrigger>
            <TabsTrigger value="dream" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">Dream</TabsTrigger>
            <TabsTrigger value="other" className="text-xs px-2 py-1.5 sm:px-3 sm:py-2 data-[state=active]:shadow-sm">其他</TabsTrigger>
          </TabsList>
          {/* 基本信息 */}
          <TabsContent value="bot" className="space-y-4">
            {botConfig && <BotInfoSection config={botConfig} onChange={setBotConfig} />}
          </TabsContent>

        {/* 人格配置 */}
        <TabsContent value="personality" className="space-y-4">
          {personalityConfig && (
            <PersonalitySection config={personalityConfig} onChange={setPersonalityConfig} />
          )}
        </TabsContent>

        {/* 聊天配置 */}
        <TabsContent value="chat" className="space-y-4">
          {chatConfig && <ChatSection config={chatConfig} onChange={setChatConfig} />}
        </TabsContent>

        {/* 表达配置 */}
        <TabsContent value="expression" className="space-y-4">
          {expressionConfig && (
            <ExpressionSection config={expressionConfig} onChange={setExpressionConfig} />
          )}
        </TabsContent>

        {/* 功能配置（合并表情、记忆、工具） */}
        <TabsContent value="features" className="space-y-4">
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
        <TabsContent value="processing" className="space-y-4">
          {keywordReactionConfig && responsePostProcessConfig && chineseTypoConfig && responseSplitterConfig && (
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
        <TabsContent value="voice" className="space-y-4">
          {voiceConfig && <VoiceSection config={voiceConfig} onChange={setVoiceConfig} />}
        </TabsContent>

        {/* 消息过滤配置 */}
        <TabsContent value="message_receive" className="space-y-4">
          {messageReceiveConfig && (
            <MessageReceiveSection config={messageReceiveConfig} onChange={setMessageReceiveConfig} />
          )}
        </TabsContent>

        {/* 服务配置 */}
        <TabsContent value="service" className="space-y-4">
          {webuiConfig && <WebUISection config={webuiConfig} onChange={setWebuiConfig} />}
          {maimMessageConfig && <MaimMessageSection config={maimMessageConfig} onChange={setMaimMessageConfig} />}
          {telemetryConfig && <TelemetrySection config={telemetryConfig} onChange={setTelemetryConfig} />}
        </TabsContent>

        {/* 实验配置 */}
        <TabsContent value="experimental" className="space-y-4">
          {experimentalConfig && (
            <ExperimentalSection config={experimentalConfig} onChange={setExperimentalConfig} />
          )}
        </TabsContent>

        {/* Dream 配置 */}
        <TabsContent value="dream" className="space-y-4">
          {dreamConfig && <DreamSection config={dreamConfig} onChange={setDreamConfig} />}
        </TabsContent>

        {/* 其他配置 */}
        <TabsContent value="other" className="space-y-4">
          {logConfig && <LogSection config={logConfig} onChange={setLogConfig} />}
          {debugConfig && <DebugSection config={debugConfig} onChange={setDebugConfig} />}
        </TabsContent>
        </Tabs>
        </>
        )}

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
