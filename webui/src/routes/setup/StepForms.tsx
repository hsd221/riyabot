// 设置向导各步骤表单组件

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Slider } from '@/components/ui/slider'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Markdown } from '@/components/ui/markdown'
import { useState } from 'react'
import {
  CheckCircle2,
  Eye,
  EyeOff,
  FileText,
  KeyRound,
  ShieldCheck,
  X,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { validatePassword } from '@/lib/password-validator'
import type {
  AgreementStatus,
  BotBasicConfig,
  PersonalityConfig,
  EmojiConfig,
  OtherBasicConfig,
} from './types'

interface PasswordSetupFormProps {
  password: string
  passwordConfirm: string
  onPasswordChange: (password: string) => void
  onPasswordConfirmChange: (password: string) => void
}

export function PasswordSetupForm({
  password,
  passwordConfirm,
  onPasswordChange,
  onPasswordConfirmChange,
}: PasswordSetupFormProps) {
  const [showPassword, setShowPassword] = useState(false)
  const [showPasswordConfirm, setShowPasswordConfirm] = useState(false)
  const validation = validatePassword(password)
  const passwordsMatch = passwordConfirm.length > 0 && password === passwordConfirm

  return (
    <div className="space-y-5">
      <div className="ios-group overflow-hidden">
        <div className="ios-row ios-row-plain items-start gap-3 py-4">
          <span className="ios-symbol ios-symbol-md ios-symbol-green mt-0.5">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="text-[15px] font-semibold leading-5 text-foreground">保护 WebUI</p>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              密码只会以加盐哈希保存，设置完成后将用于登录控制台。
            </p>
          </div>
        </div>

        <div className="ios-row ios-row-plain min-h-[76px] flex-col !items-stretch gap-2 sm:flex-row sm:!items-center">
          <Label htmlFor="setup-password" className="shrink-0 text-[15px] font-normal sm:w-24">
            设置密码
          </Label>
          <div className="relative min-w-0 flex-1">
            <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="setup-password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(event) => onPasswordChange(event.target.value)}
              className="h-11 rounded-[12px] bg-muted/60 pl-10 pr-11 shadow-none"
              placeholder="8-128 位，可使用空格与符号"
              autoComplete="new-password"
              minLength={8}
              maxLength={128}
              aria-describedby="setup-password-rules"
              autoFocus
            />
            <button
              type="button"
              className="ios-touch absolute right-1 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-accent"
              onClick={() => setShowPassword((visible) => !visible)}
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
              title={showPassword ? '隐藏密码' : '显示密码'}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <div className="ios-row ios-row-plain min-h-[76px] flex-col !items-stretch gap-2 sm:flex-row sm:!items-center">
          <Label
            htmlFor="setup-password-confirm"
            className="shrink-0 text-[15px] font-normal sm:w-24"
          >
            确认密码
          </Label>
          <div className="relative min-w-0 flex-1">
            <Input
              id="setup-password-confirm"
              type={showPasswordConfirm ? 'text' : 'password'}
              value={passwordConfirm}
              onChange={(event) => onPasswordConfirmChange(event.target.value)}
              className="h-11 rounded-[12px] bg-muted/60 pr-11 shadow-none"
              placeholder="再次输入密码"
              autoComplete="new-password"
              minLength={8}
              maxLength={128}
            />
            <button
              type="button"
              className="ios-touch absolute right-1 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-accent"
              onClick={() => setShowPasswordConfirm((visible) => !visible)}
              aria-label={showPasswordConfirm ? '隐藏确认密码' : '显示确认密码'}
              title={showPasswordConfirm ? '隐藏确认密码' : '显示确认密码'}
            >
              {showPasswordConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
      </div>

      <div id="setup-password-rules" className="ios-group grid gap-3 p-4 sm:grid-cols-2">
        {validation.rules.map((rule) => (
          <div key={rule.id} className="flex min-w-0 items-center gap-2 text-sm">
            {rule.passed ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-[rgb(36_138_61)] dark:text-[rgb(99_230_131)]" />
            ) : (
              <XCircle className="h-4 w-4 shrink-0 text-muted-foreground" />
            )}
            <span
              className={cn(
                rule.passed
                  ? 'text-[rgb(36_138_61)] dark:text-[rgb(99_230_131)]'
                  : 'text-muted-foreground'
              )}
            >
              {rule.label}
            </span>
          </div>
        ))}
        <div className="flex min-w-0 items-center gap-2 text-sm">
          {passwordsMatch ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-[rgb(36_138_61)] dark:text-[rgb(99_230_131)]" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span
            className={cn(
              passwordsMatch
                ? 'text-[rgb(36_138_61)] dark:text-[rgb(99_230_131)]'
                : 'text-muted-foreground'
            )}
          >
            两次输入一致
          </span>
        </div>
      </div>
    </div>
  )
}

// ====== 协议确认 ======
interface AgreementFormProps {
  status: AgreementStatus | null
  acceptedEula: boolean
  acceptedPrivacy: boolean
  onAcceptedEulaChange: (checked: boolean) => void
  onAcceptedPrivacyChange: (checked: boolean) => void
}

const agreementMarkdownClass =
  'max-w-none overflow-hidden break-words text-[15px] leading-6 text-foreground/90 dark:prose-invert [&_*]:max-w-full [&_h1]:!mb-4 [&_h1]:!mt-0 [&_h1]:!break-words [&_h1]:!text-[20px] [&_h1]:!font-semibold [&_h1]:!leading-[1.22] [&_h1]:!tracking-normal sm:[&_h1]:!text-[22px] [&_h2]:!mb-2.5 [&_h2]:!mt-5 [&_h2]:!break-words [&_h2]:!text-[17px] [&_h2]:!font-semibold [&_h2]:!leading-[1.3] [&_h3]:!mb-2 [&_h3]:!mt-4 [&_h3]:!break-words [&_h3]:!text-[15px] [&_h3]:!font-semibold [&_h3]:!leading-[1.38] [&_li]:!my-1.5 [&_li]:!leading-6 [&_ol]:!my-3 [&_p]:!my-3 [&_p]:!break-words [&_p]:!leading-6 [&_strong]:!font-medium [&_strong]:!text-foreground'

export function AgreementForm({
  status,
  acceptedEula,
  acceptedPrivacy,
  onAcceptedEulaChange,
  onAcceptedPrivacyChange,
}: AgreementFormProps) {
  if (!status) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        正在读取协议内容...
      </div>
    )
  }

  const allConfirmed = status.eula.confirmed && status.privacy.confirmed
  const readyToContinue = acceptedEula && acceptedPrivacy

  return (
    <div className="min-w-0 space-y-4 sm:space-y-6">
      <div
        className={
          readyToContinue
            ? 'ios-group flex min-w-0 items-start gap-3 border-emerald-200/70 bg-emerald-50/70 px-4 py-3.5 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-100'
            : 'ios-group flex min-w-0 items-start gap-3 px-4 py-3.5'
        }
      >
        <span
          className={
            readyToContinue
              ? 'mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-[9px] bg-emerald-500 text-white shadow-[0_4px_10px_rgba(16,185,129,0.22)]'
              : 'mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-[9px] bg-[#007AFF] text-white shadow-[0_4px_10px_rgba(0,122,255,0.2)]'
          }
        >
          {readyToContinue ? <ShieldCheck className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
        </span>
        <span className="min-w-0">
          <span className="block text-[15px] font-medium leading-5">
            {readyToContinue ? '协议已勾选' : '请阅读并确认协议'}
          </span>
          <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">
            {readyToContinue
              ? '点击下一步后会继续当前配置流程。'
              : allConfirmed
                ? '系统检测到本机曾确认过此版本，但本次向导仍需要您显式勾选后继续。'
                : '请阅读并同意当前版本的最终用户许可协议和隐私条款后继续。'}
          </span>
        </span>
      </div>

      <Tabs defaultValue="eula" className="w-full min-w-0">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="eula">许可协议</TabsTrigger>
          <TabsTrigger value="privacy">隐私条款</TabsTrigger>
        </TabsList>
        <TabsContent value="eula" className="mt-3 sm:mt-4">
          <div data-setup-panel="agreement-document" className="ios-group min-w-0 overflow-hidden">
            <ScrollArea className="h-[clamp(128px,16svh,320px)] min-w-0 p-4 sm:h-[clamp(240px,31svh,460px)] sm:p-6">
              <Markdown className={agreementMarkdownClass}>{status.eula.content}</Markdown>
            </ScrollArea>
          </div>
        </TabsContent>
        <TabsContent value="privacy" className="mt-3 sm:mt-4">
          <div data-setup-panel="agreement-document" className="ios-group min-w-0 overflow-hidden">
            <ScrollArea className="h-[clamp(128px,16svh,320px)] min-w-0 p-4 sm:h-[clamp(240px,31svh,460px)] sm:p-6">
              <Markdown className={agreementMarkdownClass}>{status.privacy.content}</Markdown>
            </ScrollArea>
          </div>
        </TabsContent>
      </Tabs>

      <div
        data-setup-panel="agreement-checkboxes"
        className="ios-group min-w-0 divide-y divide-border/60 overflow-hidden"
      >
        <label className="ios-touch flex min-h-16 items-start gap-3 px-5 py-4 text-sm leading-relaxed hover:bg-accent/70">
          <Checkbox
            checked={acceptedEula}
            onCheckedChange={(checked) => onAcceptedEulaChange(checked === true)}
            className="mt-0.5"
          />
          <span>
            我已阅读并同意《{status.eula.title}》
            <span className="hidden text-xs text-muted-foreground sm:block">
              当前版本哈希：{status.eula.hash}
            </span>
          </span>
        </label>
        <label className="ios-touch flex min-h-16 items-start gap-3 px-5 py-4 text-sm leading-relaxed hover:bg-accent/70">
          <Checkbox
            checked={acceptedPrivacy}
            onCheckedChange={(checked) => onAcceptedPrivacyChange(checked === true)}
            className="mt-0.5"
          />
          <span>
            我已阅读并同意《{status.privacy.title}》
            <span className="hidden text-xs text-muted-foreground sm:block">
              当前版本哈希：{status.privacy.hash}
            </span>
          </span>
        </label>
      </div>
    </div>
  )
}

// ====== 步骤1：Bot基础配置 ======
interface BotBasicFormProps {
  config: BotBasicConfig
  onChange: (config: BotBasicConfig) => void
}

export function BotBasicForm({ config, onChange }: BotBasicFormProps) {
  const handleAddAlias = (alias: string) => {
    if (alias.trim() && !config.alias_names.includes(alias.trim())) {
      onChange({
        ...config,
        alias_names: [...config.alias_names, alias.trim()],
      })
    }
  }

  const handleRemoveAlias = (index: number) => {
    onChange({
      ...config,
      alias_names: config.alias_names.filter((_, i) => i !== index),
    })
  }

  return (
    <div className="space-y-5">
      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="qq_account">QQ账号 *</Label>
        <Input
          id="qq_account"
          type="number"
          placeholder="请输入机器人的QQ账号"
          value={config.qq_account || ''}
          onChange={(e) => onChange({ ...config, qq_account: Number(e.target.value) })}
        />
        <p className="text-xs text-muted-foreground">机器人登录使用的QQ账号</p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="nickname">昵称 *</Label>
        <Input
          id="nickname"
          placeholder="请输入机器人的昵称"
          value={config.nickname}
          onChange={(e) => onChange({ ...config, nickname: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">机器人的主要称呼名称</p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label>别名</Label>
        <div className="mb-2 flex flex-wrap gap-2">
          {config.alias_names.map((alias, index) => (
            <Badge key={index} variant="secondary" className="gap-1">
              {alias}
              <button
                type="button"
                onClick={() => handleRemoveAlias(index)}
                className="hover:text-destructive ml-1"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            id="alias_input"
            placeholder="输入别名后按回车添加"
            onKeyPress={(e) => {
              if (e.key === 'Enter') {
                handleAddAlias((e.target as HTMLInputElement).value)
                ;(e.target as HTMLInputElement).value = ''
              }
            }}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              const input = document.getElementById('alias_input') as HTMLInputElement
              if (input) {
                handleAddAlias(input.value)
                input.value = ''
              }
            }}
          >
            添加
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">机器人的其他称呼，可以添加多个</p>
      </div>
    </div>
  )
}

// ====== 步骤2：人格配置 ======
interface PersonalityFormProps {
  config: PersonalityConfig
  onChange: (config: PersonalityConfig) => void
}

export function PersonalityForm({ config, onChange }: PersonalityFormProps) {
  return (
    <div className="space-y-5">
      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="personality">人格特征 *</Label>
        <Textarea
          id="personality"
          placeholder="描述机器人的人格特质和身份特征（建议120字以内）"
          value={config.personality}
          onChange={(e) => onChange({ ...config, personality: e.target.value })}
          rows={3}
        />
        <p className="text-xs text-muted-foreground">
          例如：是一个女大学生，现在在读大二，会刷贴吧
        </p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="reply_style">表达风格 *</Label>
        <Textarea
          id="reply_style"
          placeholder="描述机器人说话的表达风格、表达习惯"
          value={config.reply_style}
          onChange={(e) => onChange({ ...config, reply_style: e.target.value })}
          rows={3}
        />
        <p className="text-xs text-muted-foreground">
          例如：回复平淡一些，简短一些，说中文，参考贴吧、知乎和微博的回复风格
        </p>
      </div>
    </div>
  )
}

// ====== 步骤3：表情包配置 ======
interface EmojiFormProps {
  config: EmojiConfig
  onChange: (config: EmojiConfig) => void
}

export function EmojiForm({ config, onChange }: EmojiFormProps) {
  return (
    <div className="space-y-5">
      <div className="ios-group space-y-3 p-5">
        <div className="flex items-center justify-between">
          <Label htmlFor="emoji_chance">表情包激活概率</Label>
          <span className="text-sm text-muted-foreground">
            {(config.emoji_chance * 100).toFixed(0)}%
          </span>
        </div>
        <Input
          id="emoji_chance"
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={config.emoji_chance}
          className="h-2 cursor-pointer bg-transparent p-0 shadow-none"
          onChange={(e) => onChange({ ...config, emoji_chance: Number(e.target.value) })}
        />
        <p className="text-xs text-muted-foreground">机器人发送表情包的概率</p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="max_reg_num">最大表情包数量</Label>
        <Input
          id="max_reg_num"
          type="number"
          min="1"
          max="200"
          value={config.max_reg_num}
          onChange={(e) => onChange({ ...config, max_reg_num: Number(e.target.value) })}
        />
        <p className="text-xs text-muted-foreground">机器人最多保存的表情包数量</p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="selection_candidate_count">最终候选数量</Label>
        <Input
          id="selection_candidate_count"
          type="number"
          min="1"
          max="30"
          value={config.selection_candidate_count}
          onChange={(event) => {
            const value = Number.parseInt(event.target.value, 10)
            if (Number.isFinite(value)) {
              onChange({
                ...config,
                selection_candidate_count: Math.max(1, Math.min(30, value)),
              })
            }
          }}
        />
      </div>

      <div className="ios-group">
        <div className="ios-row">
          <div className="space-y-1">
            <Label htmlFor="do_replace">达到最大数量时替换</Label>
            <p className="text-xs text-muted-foreground">
              开启后会删除旧表情包，关闭则不再收集新表情包
            </p>
          </div>
          <Switch
            id="do_replace"
            checked={config.do_replace}
            onCheckedChange={(checked) => onChange({ ...config, do_replace: checked })}
          />
        </div>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="check_interval">检查间隔（分钟）</Label>
        <Input
          id="check_interval"
          type="number"
          min="1"
          max="120"
          value={config.check_interval}
          onChange={(e) => onChange({ ...config, check_interval: Number(e.target.value) })}
        />
        <p className="text-xs text-muted-foreground">检查表情包注册、破损、删除的时间间隔</p>
      </div>

      <Separator className="hidden" />

      <div className="ios-group">
        <div className="ios-row">
          <div className="space-y-1">
            <Label htmlFor="steal_emoji">偷取表情包</Label>
            <p className="text-xs text-muted-foreground">允许机器人将一些表情包据为己有</p>
          </div>
          <Switch
            id="steal_emoji"
            checked={config.steal_emoji}
            onCheckedChange={(checked) => onChange({ ...config, steal_emoji: checked })}
          />
        </div>
        <div className="ios-row">
          <div className="space-y-1">
            <Label htmlFor="content_filtration">启用表情包过滤</Label>
            <p className="text-xs text-muted-foreground">只保存符合要求的表情包</p>
          </div>
          <Switch
            id="content_filtration"
            checked={config.content_filtration}
            onCheckedChange={(checked) => onChange({ ...config, content_filtration: checked })}
          />
        </div>
      </div>

      <div className="ios-group">
        <div className="ios-row">
          <Label htmlFor="usage_scene_enabled">学习真人使用场景</Label>
          <Switch
            id="usage_scene_enabled"
            checked={config.usage_scene_enabled}
            onCheckedChange={(checked) => onChange({ ...config, usage_scene_enabled: checked })}
          />
        </div>

        {config.usage_scene_enabled && (
          <div className="space-y-4 border-t p-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="usage_scene_context_messages">学习上下文消息数</Label>
                <Input
                  id="usage_scene_context_messages"
                  type="number"
                  min="1"
                  max="32"
                  value={config.usage_scene_context_messages}
                  onChange={(event) => {
                    const value = Number.parseInt(event.target.value, 10)
                    if (Number.isFinite(value)) {
                      onChange({
                        ...config,
                        usage_scene_context_messages: Math.max(1, Math.min(32, value)),
                      })
                    }
                  }}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="usage_scene_max_scenes">单表情场景软上限</Label>
                <Input
                  id="usage_scene_max_scenes"
                  type="number"
                  min="1"
                  max="32"
                  value={config.usage_scene_max_scenes}
                  onChange={(event) => {
                    const value = Number.parseInt(event.target.value, 10)
                    if (Number.isFinite(value)) {
                      onChange({
                        ...config,
                        usage_scene_max_scenes: Math.max(1, Math.min(32, value)),
                      })
                    }
                  }}
                />
              </div>
            </div>

            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-4">
                <Label htmlFor="usage_scene_weight">初筛场景权重</Label>
                <span className="text-sm tabular-nums text-muted-foreground">
                  {Math.round(config.usage_scene_weight * 100)}%
                </span>
              </div>
              <Slider
                id="usage_scene_weight"
                value={[config.usage_scene_weight]}
                min={0}
                max={1}
                step={0.05}
                onValueChange={(values) => onChange({ ...config, usage_scene_weight: values[0] })}
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>仅情感</span>
                <span>仅场景</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {config.content_filtration && (
        <div className="ios-group space-y-3 p-5">
          <Label htmlFor="filtration_prompt">过滤要求</Label>
          <Input
            id="filtration_prompt"
            placeholder="例如：符合公序良俗"
            value={config.filtration_prompt}
            onChange={(e) => onChange({ ...config, filtration_prompt: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">描述表情包应该符合的要求</p>
        </div>
      )}
    </div>
  )
}

// ====== 步骤4：其他基础配置 ======
interface OtherBasicFormProps {
  config: OtherBasicConfig
  onChange: (config: OtherBasicConfig) => void
}

export function OtherBasicForm({ config, onChange }: OtherBasicFormProps) {
  return (
    <div className="ios-group">
      <div className="ios-row">
        <div className="space-y-1">
          <Label htmlFor="enable_tool">启用工具系统</Label>
          <p className="text-xs text-muted-foreground">允许机器人使用各种工具增强功能</p>
        </div>
        <Switch
          id="enable_tool"
          checked={config.enable_tool}
          onCheckedChange={(checked) => onChange({ ...config, enable_tool: checked })}
        />
      </div>

      <div className="ios-row">
        <div className="space-y-1">
          <Label htmlFor="all_global_jargon">启用全局黑话模式</Label>
          <p className="text-xs text-muted-foreground">允许机器人学习和使用群组黑话</p>
        </div>
        <Switch
          id="all_global_jargon"
          checked={config.all_global_jargon}
          onCheckedChange={(checked) => onChange({ ...config, all_global_jargon: checked })}
        />
      </div>
    </div>
  )
}
