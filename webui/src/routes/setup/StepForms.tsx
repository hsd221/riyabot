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
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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

  return (
    <div className="space-y-6">
      {allConfirmed ? (
        <Alert className="border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">
          <ShieldCheck className="h-4 w-4" />
          <AlertTitle>协议已确认</AlertTitle>
          <AlertDescription>
            当前版本的最终用户许可协议和隐私条款已经确认。
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <FileText className="h-4 w-4" />
          <AlertTitle>需要确认协议</AlertTitle>
          <AlertDescription>
            请阅读并同意当前版本的最终用户许可协议和隐私条款后继续。
          </AlertDescription>
        </Alert>
      )}

      <Tabs defaultValue="eula" className="w-full">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="eula">许可协议</TabsTrigger>
          <TabsTrigger value="privacy">隐私条款</TabsTrigger>
        </TabsList>
        <TabsContent value="eula" className="mt-4">
          <div className="rounded-md border bg-background">
            <ScrollArea className="h-[320px] p-4">
              <Markdown className="prose-sm dark:prose-invert max-w-none">
                {status.eula.content}
              </Markdown>
            </ScrollArea>
          </div>
        </TabsContent>
        <TabsContent value="privacy" className="mt-4">
          <div className="rounded-md border bg-background">
            <ScrollArea className="h-[320px] p-4">
              <Markdown className="prose-sm dark:prose-invert max-w-none">
                {status.privacy.content}
              </Markdown>
            </ScrollArea>
          </div>
        </TabsContent>
      </Tabs>

      <div className="space-y-3 rounded-md border bg-muted/30 p-4">
        <label className="flex items-start gap-3 text-sm">
          <Checkbox
            checked={status.eula.confirmed || acceptedEula}
            disabled={status.eula.confirmed}
            onCheckedChange={(checked) => onAcceptedEulaChange(checked === true)}
            className="mt-0.5"
          />
          <span>
            我已阅读并同意《{status.eula.title}》
            <span className="block text-xs text-muted-foreground">
              当前版本哈希：{status.eula.hash}
            </span>
          </span>
        </label>
        <label className="flex items-start gap-3 text-sm">
          <Checkbox
            checked={status.privacy.confirmed || acceptedPrivacy}
            disabled={status.privacy.confirmed}
            onCheckedChange={(checked) => onAcceptedPrivacyChange(checked === true)}
            className="mt-0.5"
          />
          <span>
            我已阅读并同意《{status.privacy.title}》
            <span className="block text-xs text-muted-foreground">
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
    <div className="space-y-6">
      <div className="space-y-3">
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

      <div className="space-y-3">
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

      <div className="space-y-3">
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
    <div className="space-y-6">
      <div className="space-y-3">
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

      <div className="space-y-3">
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

      <div className="space-y-3">
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
    <div className="space-y-6">
      <div className="space-y-3">
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
          onChange={(e) =>
            onChange({ ...config, emoji_chance: Number(e.target.value) })
          }
        />
        <p className="text-xs text-muted-foreground">
          机器人发送表情包的概率
        </p>
      </div>

      <div className="space-y-3">
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

      <div className="flex items-center justify-between">
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

      <div className="space-y-3">
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

      <Separator />

      <div className="flex items-center justify-between">
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

      <div className="flex items-center justify-between">
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

      {config.content_filtration && (
        <div className="space-y-3">
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
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

      <div className="flex items-center justify-between">
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
