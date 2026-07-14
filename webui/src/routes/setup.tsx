import { useState, useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  Sparkles,
  Check,
  ArrowRight,
  ChevronRight,
  CheckCircle2,
  SkipForward,
  Bot,
  User,
  Smile,
  Settings,
  Loader2,
  ShieldCheck,
  Server,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
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
import { cn } from '@/lib/utils'
import { APP_NAME } from '@/lib/version'
import { useToast } from '@/hooks/use-toast'
import type {
  AgreementStatus,
  SetupStep,
  BotBasicConfig,
  PersonalityConfig,
  EmojiConfig,
  OtherBasicConfig,
} from './setup/types'
import {
  AgreementForm,
  BotBasicForm,
  PersonalityForm,
  EmojiForm,
  OtherBasicForm,
} from './setup/StepForms'
import {
  loadAgreementStatus,
  loadBotBasicConfig,
  loadPersonalityConfig,
  loadEmojiConfig,
  loadOtherBasicConfig,
  saveBotBasicConfig,
  savePersonalityConfig,
  saveEmojiConfig,
  saveOtherBasicConfig,
  confirmAgreement,
  completeSetup,
} from './setup/api'
import { restartRiyaBot, getRiyaBotStatus } from '@/lib/system-api'

export function SetupPage() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const [currentStep, setCurrentStep] = useState(0)
  const [isCompleting, setIsCompleting] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [stepDialogOpen, setStepDialogOpen] = useState(false)

  const [agreementStatus, setAgreementStatus] = useState<AgreementStatus | null>(null)
  const [acceptedEula, setAcceptedEula] = useState(false)
  const [acceptedPrivacy, setAcceptedPrivacy] = useState(false)

  // Bot基础信息
  const [botBasic, setBotBasic] = useState<BotBasicConfig>({
    qq_account: 0,
    nickname: '',
    alias_names: [],
  })

  // 人格配置
  const [personality, setPersonality] = useState<PersonalityConfig>({
    personality: '是一个女大学生，现在在读大二，会刷贴吧。',
    reply_style:
      '请回复的平淡一些，简短一些，说中文，不要刻意突出自身学科背景。可以参考贴吧，知乎和微博的回复风格。',
    plan_style:
      '1.思考**所有**的可用的action中的**每个动作**是否符合当下条件，如果动作使用条件符合聊天内容就使用\n2.如果相同的内容已经被执行，请不要重复执行\n3.请控制你的发言频率，不要太过频繁的发言\n4.如果有人对你感到厌烦，请减少回复\n5.如果有人对你进行攻击，或者情绪激动，请你以合适的方法应对',
  })

  // 表情包配置
  const [emoji, setEmoji] = useState<EmojiConfig>({
    emoji_chance: 0.4,
    max_reg_num: 40,
    do_replace: true,
    check_interval: 10,
    steal_emoji: true,
    content_filtration: false,
    filtration_prompt: '符合公序良俗',
  })

  // 其他基础配置
  const [otherBasic, setOtherBasic] = useState<OtherBasicConfig>({
    enable_tool: true,
    all_global_jargon: true,
  })

  // 重启相关状态
  const [isRestarting, setIsRestarting] = useState(false)
  const [restartProgress, setRestartProgress] = useState('')

  const steps: SetupStep[] = [
    {
      id: 'agreement',
      title: '协议确认',
      description: '阅读并同意许可协议和隐私条款',
      icon: ShieldCheck,
    },
    {
      id: 'bot-basic',
      title: 'Bot基础',
      description: '配置机器人的基本信息',
      icon: Bot,
    },
    {
      id: 'personality',
      title: '人格配置',
      description: '定义机器人的性格和说话风格',
      icon: User,
    },
    {
      id: 'emoji',
      title: '表情包',
      description: '配置表情包相关设置',
      icon: Smile,
    },
    {
      id: 'other',
      title: '其他设置',
      description: '工具、黑话模式等配置',
      icon: Settings,
    },
    {
      id: 'model-config',
      title: '模型配置',
      description: '添加模型厂商、模型和任务分配',
      icon: Server,
    },
  ]

  const progress = ((currentStep + 1) / steps.length) * 100
  const currentStepInfo = steps[currentStep]

  // 加载现有配置
  useEffect(() => {
    const loadConfigs = async () => {
      try {
        setIsLoading(true)

        // 并行加载所有配置
        const [agreement, bot, personality, emoji, other] = await Promise.all([
          loadAgreementStatus(),
          loadBotBasicConfig(),
          loadPersonalityConfig(),
          loadEmojiConfig(),
          loadOtherBasicConfig(),
        ])

        setAgreementStatus(agreement)
        setAcceptedEula(false)
        setAcceptedPrivacy(false)
        setBotBasic(bot)
        setPersonality(personality)
        setEmoji(emoji)
        setOtherBasic(other)
      } catch (error) {
        toast({
          title: '加载配置失败',
          description: error instanceof Error ? error.message : '无法加载现有配置，将使用默认值',
          variant: 'destructive',
        })
      } finally {
        setIsLoading(false)
      }
    }

    loadConfigs()
  }, [toast])

  // 保存当前步骤配置
  const saveCurrentStep = async () => {
    setIsSaving(true)
    try {
      const step = steps[currentStep]

      switch (step.id) {
        case 'agreement':
          if (!agreementStatus) {
            throw new Error('协议状态尚未加载')
          }

          if (!acceptedEula || !acceptedPrivacy) {
            toast({
              title: '请先确认协议',
              description: '需要同时同意最终用户许可协议和隐私条款后才能继续',
              variant: 'destructive',
            })
            return false
          }

          if (!(agreementStatus.eula.confirmed && agreementStatus.privacy.confirmed)) {
            setAgreementStatus(
              await confirmAgreement(agreementStatus.eula.hash, agreementStatus.privacy.hash)
            )
          }
          break
        case 'bot-basic':
          await saveBotBasicConfig(botBasic)
          break
        case 'personality':
          await savePersonalityConfig(personality)
          break
        case 'emoji':
          await saveEmojiConfig(emoji)
          break
        case 'other':
          await saveOtherBasicConfig(otherBasic)
          break
        case 'model-config':
          return true
      }

      toast({
        title: '保存成功',
        description: `${steps[currentStep].title}配置已保存`,
      })
      return true
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
      return false
    } finally {
      setIsSaving(false)
    }
  }

  const handleNext = async () => {
    // 保存当前步骤
    const saved = await saveCurrentStep()
    if (!saved) return

    // 进入下一步
    if (currentStep < steps.length - 1) {
      setCurrentStep(currentStep + 1)
    }
  }

  const handlePrevious = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1)
    }
  }

  const handleComplete = async () => {
    setIsCompleting(true)
    setIsRestarting(true)

    try {
      // 1. 保存最后一步的配置
      setRestartProgress('正在保存基础配置...')
      const saved = await saveCurrentStep()
      if (!saved) {
        setIsCompleting(false)
        setIsRestarting(false)
        return
      }

      // 2. 标记设置完成
      setRestartProgress('正在完成初始化...')
      await completeSetup()

      // 3. 触发主程序重启
      setRestartProgress('正在重启主程序...')
      await restartRiyaBot()

      toast({
        title: '配置完成',
        description: '主程序正在重启以应用新配置...',
      })

      // 4. 轮询检查主程序是否重启成功
      setRestartProgress('等待主程序重启完成...')
      const maxAttempts = 60 // 最多等待60秒
      let attempt = 0
      let restartSuccess = false

      while (attempt < maxAttempts && !restartSuccess) {
        await new Promise((resolve) => setTimeout(resolve, 1000)) // 每秒检查一次

        try {
          const status = await getRiyaBotStatus()
          if (status.running) {
            restartSuccess = true
            setRestartProgress('重启成功！正在跳转...')
          }
        } catch {
          // 重启过程中API会暂时不可用,这是正常的
          attempt++
        }
      }

      if (!restartSuccess) {
        throw new Error('重启超时,请手动检查主程序状态')
      }

      // 5. 导航到首页
      setTimeout(() => {
        navigate({ to: '/' })
      }, 1000)
    } catch (error) {
      setIsRestarting(false)
      toast({
        title: '配置失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setIsCompleting(false)
    }
  }

  const handleSkip = async () => {
    try {
      if (agreementStatus?.agreement_required) {
        setCurrentStep(0)
        toast({
          title: '请先确认协议',
          description: '协议确认完成后才可以跳过配置向导',
          variant: 'destructive',
        })
        return
      }

      await completeSetup()
      navigate({ to: '/' })
    } catch (error) {
      toast({
        title: '跳过失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }

  // 渲染当前步骤的表单
  const renderStepForm = () => {
    switch (steps[currentStep].id) {
      case 'agreement':
        return (
          <AgreementForm
            status={agreementStatus}
            acceptedEula={acceptedEula}
            acceptedPrivacy={acceptedPrivacy}
            onAcceptedEulaChange={setAcceptedEula}
            onAcceptedPrivacyChange={setAcceptedPrivacy}
          />
        )
      case 'bot-basic':
        return <BotBasicForm config={botBasic} onChange={setBotBasic} />
      case 'personality':
        return <PersonalityForm config={personality} onChange={setPersonality} />
      case 'emoji':
        return <EmojiForm config={emoji} onChange={setEmoji} />
      case 'other':
        return <OtherBasicForm config={otherBasic} onChange={setOtherBasic} />
      case 'model-config':
        return (
          <div className="space-y-4">
            <div className="ios-group p-5 text-sm leading-relaxed text-muted-foreground">
              模型配置不再预设任何厂商。请按自己的服务商和模型名称完成配置后，再返回此向导完成初始化。
            </div>
            <div className="ios-group divide-y divide-border/70 overflow-hidden">
              <button
                type="button"
                className="ios-touch flex min-h-16 w-full items-center justify-between gap-4 px-5 py-4 text-left hover:bg-accent"
                onClick={() => navigate({ to: '/config/modelProvider' })}
              >
                <div>
                  <div className="font-medium">AI模型厂商配置</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    添加 API Base URL、Key 和客户端类型
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
              <button
                type="button"
                className="ios-touch flex min-h-16 w-full items-center justify-between gap-4 px-5 py-4 text-left hover:bg-accent"
                onClick={() => navigate({ to: '/config/model' })}
              >
                <div>
                  <div className="font-medium">模型管理与分配</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    添加模型并分配给回复、规划、工具等任务
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </div>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <div className="ios-page min-h-screen">
      {/* 重启遮罩层 */}
      {isRestarting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-xl">
          <div className="ios-card mx-auto flex w-full max-w-md flex-col items-center space-y-6 p-6 text-center sm:p-8">
            <div className="flex h-20 w-20 items-center justify-center rounded-[22px] bg-[rgb(0_122_255_/_0.11)] shadow-[0_1px_0_rgba(255,255,255,0.64)_inset]">
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
            </div>
            <div className="space-y-2">
              <h2 className="text-2xl font-semibold">正在重启主程序</h2>
              <p className="text-muted-foreground">{restartProgress}</p>
            </div>
            <div className="w-full">
              <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                <div className="h-full w-full animate-pulse bg-primary" />
              </div>
            </div>
            <p className="text-sm text-muted-foreground">请稍候，这可能需要一分钟...</p>
          </div>
        </div>
      )}

      {/* 加载状态 */}
      {isLoading ? (
        <div className="flex min-h-[calc(100vh-2rem)] items-center justify-center">
          <div className="ios-card w-full max-w-sm p-6 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-[18px] bg-[rgb(0_122_255_/_0.11)] shadow-[0_1px_0_rgba(255,255,255,0.64)_inset]">
              <Loader2 className="h-7 w-7 animate-spin text-primary" />
            </div>
            <p className="text-lg font-semibold">加载配置中...</p>
            <p className="mt-2 text-sm text-muted-foreground">正在读取现有配置</p>
          </div>
        </div>
      ) : (
        <>
          {/* 主要内容 */}
          <div className="mx-auto grid h-[calc(100svh-2.5rem)] w-full min-w-0 max-w-[120rem] grid-rows-[auto_minmax(0,1fr)] gap-4 overflow-hidden sm:gap-5">
            {/* 头部 */}
            <div className="flex min-w-0 items-center justify-between gap-3 sm:gap-4">
              <div className="flex min-w-0 items-center gap-3 sm:gap-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px] bg-card/80 shadow-[0_1px_1px_rgba(255,255,255,0.7)_inset,0_8px_22px_rgba(31,41,55,0.04)] backdrop-blur-xl sm:h-14 sm:w-14">
                  <Sparkles
                    className="h-5 w-5 text-primary sm:h-6 sm:w-6"
                    strokeWidth={2}
                    fill="none"
                  />
                </div>
                <div className="min-w-0">
                  <h1 className="truncate text-[22px] font-semibold leading-tight tracking-normal sm:text-3xl">
                    首次配置向导
                  </h1>
                  <p className="ios-subtitle line-clamp-2">让我们一起完成 {APP_NAME} 的初始配置</p>
                </div>
              </div>
              <div className="hidden min-w-56 rounded-[18px] border border-black/[0.025] bg-white/[0.78] px-4 py-3 shadow-[0_1px_0_rgba(255,255,255,0.72)_inset,0_10px_24px_rgba(31,41,55,0.05),0_1px_2px_rgba(0,0,0,0.025)] backdrop-blur-2xl dark:border-white/10 dark:bg-white/[0.08] sm:block">
                <div className="mb-2 flex items-center justify-between text-sm">
                  <span className="font-medium text-foreground">
                    步骤 {currentStep + 1} / {steps.length}
                  </span>
                  <span className="font-semibold text-primary">{Math.round(progress)}%</span>
                </div>
                <Progress value={progress} className="h-1.5" />
              </div>
            </div>

            <div className="grid min-h-0 min-w-0 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)] lg:gap-5">
              {/* iPad / desktop 步骤栏 */}
              <aside className="ios-card hidden min-h-0 flex-col overflow-hidden bg-card/80 backdrop-blur-xl lg:flex">
                <div className="border-b border-border/70 px-5 py-4">
                  <p className="text-sm font-semibold">配置步骤</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    按顺序完成必要配置
                  </p>
                </div>
                <div className="ios-scrollbar-none flex-1 overflow-y-auto p-2">
                  {steps.map((step, index) => {
                    const Icon = step.icon
                    const isActive = index === currentStep
                    const isDone = index < currentStep
                    return (
                      <button
                        key={step.id}
                        type="button"
                        onClick={() => index <= currentStep && setCurrentStep(index)}
                        disabled={index > currentStep}
                        className={cn(
                          'ios-touch relative flex min-h-16 w-full items-center gap-3 rounded-[15px] px-4 py-3 text-left disabled:cursor-not-allowed',
                          isActive
                            ? 'bg-muted/90 text-foreground shadow-[inset_0_0_0_1px_rgba(0,0,0,0.03)]'
                            : isDone
                              ? 'text-foreground hover:bg-muted/70'
                              : 'text-muted-foreground'
                        )}
                      >
                        {isActive && (
                          <span className="absolute inset-y-3 left-1 w-1 rounded-full bg-primary" />
                        )}
                        <div
                          className={cn(
                            'grid h-9 w-9 shrink-0 place-items-center rounded-[10px] transition-all duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)]',
                            isActive
                              ? 'bg-primary text-primary-foreground shadow-[0_5px_12px_hsl(var(--primary)_/_0.24)]'
                              : isDone
                                ? 'bg-[rgb(52_199_89)] text-white shadow-[0_5px_12px_rgba(52,199,89,0.24)]'
                                : 'bg-secondary text-muted-foreground/90 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] dark:bg-white/[0.08] dark:text-foreground/65 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]'
                          )}
                        >
                          {isDone ? (
                            <Check className="h-[18px] w-[18px]" strokeWidth={3} fill="none" />
                          ) : (
                            <Icon className="h-[18px] w-[18px]" strokeWidth={2.75} fill="none" />
                          )}
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold">{step.title}</div>
                          <div className="mt-0.5 line-clamp-2 text-xs leading-snug text-muted-foreground">
                            {step.description}
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </aside>

              <div className="flex min-h-0 min-w-0 flex-col gap-4">
                {/* 手机 / 窄屏步骤条 */}
                <div className="lg:hidden">
                  <div className="ios-group overflow-hidden">
                    <div className="px-4 py-3">
                      <div className="mb-2 flex items-center justify-between text-sm">
                        <span className="font-medium">
                          步骤 {currentStep + 1} / {steps.length}
                        </span>
                        <span className="font-semibold text-primary">{Math.round(progress)}%</span>
                      </div>
                      <Progress value={progress} className="h-1.5" />
                    </div>

                    <Dialog open={stepDialogOpen} onOpenChange={setStepDialogOpen}>
                      <DialogTrigger asChild>
                        <button
                          type="button"
                          className="ios-row ios-touch min-h-[66px] w-full text-left"
                        >
                          <span className="flex min-w-0 items-center gap-3">
                            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-primary text-primary-foreground shadow-[0_5px_12px_hsl(var(--primary)_/_0.24)]">
                              <currentStepInfo.icon
                                className="h-[18px] w-[18px]"
                                strokeWidth={2.75}
                                fill="none"
                              />
                            </span>
                            <span className="min-w-0">
                              <span className="block text-[16px] font-medium leading-6">
                                {currentStepInfo.title}
                              </span>
                              <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                                {currentStepInfo.description}
                              </span>
                            </span>
                          </span>
                          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                        </button>
                      </DialogTrigger>
                      <DialogContent className="bottom-0 left-0 top-auto max-h-[82vh] w-full max-w-none translate-x-0 translate-y-0 gap-4 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 p-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:hidden">
                        <DialogHeader className="px-5 pb-1 pt-5">
                          <DialogTitle>配置步骤</DialogTitle>
                          <DialogDescription>查看当前向导进度</DialogDescription>
                        </DialogHeader>
                        <div className="px-5 pb-5">
                          <div className="ios-group overflow-hidden">
                            {steps.map((step, index) => {
                              const Icon = step.icon
                              const isActive = index === currentStep
                              const isDone = index < currentStep
                              return (
                                <button
                                  key={step.id}
                                  type="button"
                                  disabled={index > currentStep}
                                  onClick={() => {
                                    if (index <= currentStep) {
                                      setCurrentStep(index)
                                      setStepDialogOpen(false)
                                    }
                                  }}
                                  className="ios-row min-h-[62px] w-full text-left transition-colors duration-[var(--motion-duration-control)] ease-[var(--motion-ease-standard)] hover:bg-accent/50 focus-visible:outline-none active:bg-accent/70 disabled:opacity-55"
                                >
                                  <span className="flex min-w-0 items-center gap-3">
                                    <span
                                      className={cn(
                                        'grid h-8 w-8 shrink-0 place-items-center rounded-[9px]',
                                        isActive
                                          ? 'bg-primary text-primary-foreground shadow-[0_4px_10px_hsl(var(--primary)_/_0.22)]'
                                          : isDone
                                            ? 'bg-[rgb(52_199_89)] text-white shadow-[0_4px_10px_rgba(52,199,89,0.22)]'
                                            : 'bg-secondary text-muted-foreground/90 dark:bg-white/[0.08] dark:text-foreground/65'
                                      )}
                                    >
                                      {isDone ? (
                                        <Check
                                          className="h-[17px] w-[17px]"
                                          strokeWidth={3}
                                          fill="none"
                                        />
                                      ) : (
                                        <Icon
                                          className="h-[17px] w-[17px]"
                                          strokeWidth={2.75}
                                          fill="none"
                                        />
                                      )}
                                    </span>
                                    <span className="min-w-0">
                                      <span className="block truncate text-[15px] font-medium leading-5">
                                        {step.title}
                                      </span>
                                      <span className="block truncate text-[13px] leading-5 text-muted-foreground">
                                        {step.description}
                                      </span>
                                    </span>
                                  </span>
                                  {isActive ? (
                                    <CheckCircle2
                                      className="h-4 w-4 shrink-0 text-primary"
                                      strokeWidth={2.5}
                                      fill="none"
                                    />
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
                  </div>
                </div>

                {/* 步骤内容面板 */}
                <Card className="flex min-h-0 min-w-0 flex-1 overflow-hidden !border-0 !bg-transparent !shadow-none !backdrop-blur-none sm:!border sm:!border-black/[0.035] sm:!bg-white/[0.78] sm:!shadow-[0_1px_1px_rgba(255,255,255,0.74)_inset,0_10px_30px_rgba(31,41,55,0.032),0_1px_2px_rgba(0,0,0,0.024)] sm:!backdrop-blur-2xl dark:sm:!border-white/10 dark:sm:!bg-white/[0.09]">
                  <CardContent className="flex min-h-0 flex-1 flex-col p-0">
                    <div className="flex min-h-0 flex-1 flex-col">
                      <div className="hidden border-b border-border/60 bg-card/55 px-5 py-5 sm:block sm:px-6">
                        <h2 className="text-xl font-semibold sm:text-2xl">
                          {steps[currentStep].title}
                        </h2>
                        <p className="mt-1 text-sm leading-relaxed text-muted-foreground sm:text-base">
                          {steps[currentStep].description}
                        </p>
                      </div>

                      {/* 表单内容 */}
                      <ScrollArea className="min-h-0 min-w-0 flex-1">
                        <div className="min-w-0 p-4 pb-28 sm:p-6">{renderStepForm()}</div>
                      </ScrollArea>
                    </div>

                    {/* 操作按钮 */}
                    <div className="ios-bottom-bar flex shrink-0 items-center justify-between gap-2 rounded-b-[22px] p-3">
                      <Button
                        variant="outline"
                        onClick={handlePrevious}
                        disabled={currentStep === 0 || isSaving}
                        className="h-12 w-20 shrink-0 px-3 text-sm sm:w-auto sm:px-5 sm:text-base"
                      >
                        上一步
                      </Button>

                      <div className="flex min-w-0 flex-1 justify-end gap-2">
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              className="h-12 w-12 shrink-0 gap-2 px-0 sm:w-auto sm:px-5"
                              disabled={isSaving || isCompleting}
                              aria-label="跳过向导"
                              title="跳过向导"
                            >
                              <SkipForward className="h-4 w-4" strokeWidth={2} fill="none" />
                              <span className="hidden sm:inline">跳过向导</span>
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>确认跳过配置向导</AlertDialogTitle>
                              <AlertDialogDescription>
                                您可以随时在系统设置中重新进入配置向导。确定要跳过吗？
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>取消</AlertDialogCancel>
                              <AlertDialogAction onClick={handleSkip}>确认跳过</AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>

                        {currentStep === steps.length - 1 ? (
                          <Button
                            onClick={handleComplete}
                            disabled={isCompleting || isSaving}
                            className="h-12 min-w-0 flex-1 px-3 text-sm sm:flex-none sm:px-8 sm:text-base"
                          >
                            {isCompleting || isSaving ? (
                              <>
                                <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                {isSaving ? '保存中...' : '完成中...'}
                              </>
                            ) : (
                              <>
                                完成配置
                                <CheckCircle2
                                  className="ml-2 h-4 w-4"
                                  strokeWidth={2}
                                  fill="none"
                                />
                              </>
                            )}
                          </Button>
                        ) : (
                          <Button
                            onClick={handleNext}
                            disabled={isSaving}
                            className="h-12 min-w-0 flex-1 px-3 text-sm sm:flex-none sm:px-8 sm:text-base"
                          >
                            {isSaving ? (
                              <>
                                <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                保存中...
                              </>
                            ) : (
                              <>
                                下一步
                                <ArrowRight className="ml-2 h-4 w-4" strokeWidth={2} fill="none" />
                              </>
                            )}
                          </Button>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
