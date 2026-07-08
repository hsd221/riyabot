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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Markdown } from '@/components/ui/markdown'
import { X, FileText, ShieldCheck } from 'lucide-react'
import type {
  AgreementStatus,
  BotBasicConfig,
  PersonalityConfig,
  EmojiConfig,
  OtherBasicConfig,
} from './types'

// ====== 步骤0：协议确认 ======
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
          {readyToContinue ? (
            <ShieldCheck className="h-4 w-4" />
          ) : (
            <FileText className="h-4 w-4" />
          )}
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

      <Tabs defaultValue="eula" className="min-w-0 w-full">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="eula">许可协议</TabsTrigger>
          <TabsTrigger value="privacy">隐私条款</TabsTrigger>
        </TabsList>
        <TabsContent value="eula" className="mt-3 sm:mt-4">
          <div
            data-setup-panel="agreement-document"
            className="ios-group min-w-0 overflow-hidden"
          >
            <ScrollArea className="h-[clamp(128px,16svh,320px)] min-w-0 p-4 sm:h-[clamp(240px,31svh,460px)] sm:p-6">
              <Markdown className={agreementMarkdownClass}>
                {status.eula.content}
              </Markdown>
            </ScrollArea>
          </div>
        </TabsContent>
        <TabsContent value="privacy" className="mt-3 sm:mt-4">
          <div
            data-setup-panel="agreement-document"
            className="ios-group min-w-0 overflow-hidden"
          >
            <ScrollArea className="h-[clamp(128px,16svh,320px)] min-w-0 p-4 sm:h-[clamp(240px,31svh,460px)] sm:p-6">
              <Markdown className={agreementMarkdownClass}>
                {status.privacy.content}
              </Markdown>
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
          onChange={(e) =>
            onChange({ ...config, qq_account: Number(e.target.value) })
          }
        />
        <p className="text-xs text-muted-foreground">
          机器人登录使用的QQ账号
        </p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="nickname">昵称 *</Label>
        <Input
          id="nickname"
          placeholder="请输入机器人的昵称"
          value={config.nickname}
          onChange={(e) => onChange({ ...config, nickname: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">
          机器人的主要称呼名称
        </p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label>别名</Label>
        <div className="flex flex-wrap gap-2 mb-2">
          {config.alias_names.map((alias, index) => (
            <Badge key={index} variant="secondary" className="gap-1">
              {alias}
              <button
                type="button"
                onClick={() => handleRemoveAlias(index)}
                className="ml-1 hover:text-destructive"
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
              const input = document.getElementById(
                'alias_input'
              ) as HTMLInputElement
              if (input) {
                handleAddAlias(input.value)
                input.value = ''
              }
            }}
          >
            添加
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          机器人的其他称呼，可以添加多个
        </p>
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

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="plan_style">群聊说话规则 *</Label>
        <Textarea
          id="plan_style"
          placeholder="机器人在群聊中的行为风格和规则"
          value={config.plan_style}
          onChange={(e) => onChange({ ...config, plan_style: e.target.value })}
          rows={4}
        />
        <p className="text-xs text-muted-foreground">
          定义机器人在群聊中如何行动，例如回复频率、条件等
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
          onChange={(e) =>
            onChange({ ...config, emoji_chance: Number(e.target.value) })
          }
        />
        <p className="text-xs text-muted-foreground">
          机器人发送表情包的概率
        </p>
      </div>

      <div className="ios-group space-y-3 p-5">
        <Label htmlFor="max_reg_num">最大表情包数量</Label>
        <Input
          id="max_reg_num"
          type="number"
          min="1"
          max="200"
          value={config.max_reg_num}
          onChange={(e) =>
            onChange({ ...config, max_reg_num: Number(e.target.value) })
          }
        />
        <p className="text-xs text-muted-foreground">
          机器人最多保存的表情包数量
        </p>
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
          onCheckedChange={(checked) =>
            onChange({ ...config, do_replace: checked })
          }
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
          onChange={(e) =>
            onChange({ ...config, check_interval: Number(e.target.value) })
          }
        />
        <p className="text-xs text-muted-foreground">
          检查表情包注册、破损、删除的时间间隔
        </p>
      </div>

      <Separator className="hidden" />

      <div className="ios-group">
      <div className="ios-row">
        <div className="space-y-1">
          <Label htmlFor="steal_emoji">偷取表情包</Label>
          <p className="text-xs text-muted-foreground">
            允许机器人将一些表情包据为己有
          </p>
        </div>
        <Switch
          id="steal_emoji"
          checked={config.steal_emoji}
          onCheckedChange={(checked) =>
            onChange({ ...config, steal_emoji: checked })
          }
        />
      </div>
      <div className="ios-row">

        <div className="space-y-1">
          <Label htmlFor="content_filtration">启用表情包过滤</Label>
          <p className="text-xs text-muted-foreground">
            只保存符合要求的表情包
          </p>
        </div>
        <Switch
          id="content_filtration"
          checked={config.content_filtration}
          onCheckedChange={(checked) =>
            onChange({ ...config, content_filtration: checked })
          }
        />
      </div>
      </div>

      {config.content_filtration && (
        <div className="ios-group space-y-3 p-5">
          <Label htmlFor="filtration_prompt">过滤要求</Label>
          <Input
            id="filtration_prompt"
            placeholder="例如：符合公序良俗"
            value={config.filtration_prompt}
            onChange={(e) =>
              onChange({ ...config, filtration_prompt: e.target.value })
            }
          />
          <p className="text-xs text-muted-foreground">
            描述表情包应该符合的要求
          </p>
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
          <p className="text-xs text-muted-foreground">
            允许机器人使用各种工具增强功能
          </p>
        </div>
        <Switch
          id="enable_tool"
          checked={config.enable_tool}
          onCheckedChange={(checked) =>
            onChange({ ...config, enable_tool: checked })
          }
        />
      </div>

      <div className="ios-row">
        <div className="space-y-1">
          <Label htmlFor="all_global_jargon">启用全局黑话模式</Label>
          <p className="text-xs text-muted-foreground">
            允许机器人学习和使用群组黑话
          </p>
        </div>
        <Switch
          id="all_global_jargon"
          checked={config.all_global_jargon}
          onCheckedChange={(checked) =>
            onChange({ ...config, all_global_jargon: checked })
          }
        />
      </div>
    </div>
  )
}
