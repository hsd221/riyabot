import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
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
  BadgePercent,
  Brain,
  MessageCircle,
  Plus,
  Sparkles,
  Trash2,
  WandSparkles,
} from 'lucide-react'
import type { PersonalityConfig } from '../types'

const destructiveIconButtonClass =
  'h-9 w-9 shrink-0 rounded-full border-[rgb(255_59_48_/_0.18)] bg-[rgb(255_59_48_/_0.08)] text-[rgb(215_0_21)] hover:bg-[rgb(255_59_48_/_0.12)] hover:text-[rgb(174_37_31)] dark:border-[rgb(255_69_58_/_0.18)] dark:bg-[rgb(255_69_58_/_0.1)] dark:text-[rgb(255_105_97)]'

interface PersonalitySectionProps {
  config: PersonalityConfig
  onChange: (config: PersonalityConfig) => void
}

interface MobileTextareaBlockProps {
  icon: React.ReactNode
  iconClassName: string
  label: string
  description?: string
  value: string
  placeholder: string
  rows: number
  onChange: (value: string) => void
}

const MobileTextareaBlock = React.memo(function MobileTextareaBlock({
  icon,
  iconClassName,
  label,
  description,
  value,
  placeholder,
  rows,
  onChange,
}: MobileTextareaBlockProps) {
  return (
    <div className="border-b border-border/70 px-4 py-4 last:border-b-0">
      <div className="flex items-start gap-3">
        <span className={`ios-symbol ios-symbol-sm mt-0.5 ${iconClassName}`}>{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-[15px] font-medium leading-tight">{label}</p>
            {description && (
              <p className="shrink-0 text-[12px] text-muted-foreground">{description}</p>
            )}
          </div>
          <Textarea
            value={value}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={rows}
            className="mt-2 min-h-0 resize-none border-0 bg-transparent px-0 py-0 text-[14px] leading-relaxed shadow-none focus-visible:ring-0"
          />
        </div>
      </div>
    </div>
  )
})

interface MobileProbabilityRowProps {
  label: string
  description: string
  value: number
  onChange: (value: string) => void
}

const MobileProbabilityRow = React.memo(function MobileProbabilityRow({
  label,
  description,
  value,
  onChange,
}: MobileProbabilityRowProps) {
  return (
    <div className="ios-row min-h-[72px]">
      <span className="flex min-w-0 items-center gap-3">
        <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
          <BadgePercent className="h-4 w-4" />
        </span>
        <span className="min-w-0">
          <span className="block text-[15px] font-medium leading-tight">{label}</span>
          <span className="mt-1 block text-[12px] leading-tight text-muted-foreground">
            {description}
          </span>
        </span>
      </span>
      <Input
        type="number"
        step="0.1"
        min="0"
        max="1"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-20 shrink-0 border-0 bg-transparent px-0 text-right shadow-none focus-visible:ring-0"
      />
    </div>
  )
})

export const PersonalitySection = React.memo(function PersonalitySection({
  config,
  onChange,
}: PersonalitySectionProps) {
  const replyStyles = config.multiple_reply_style ?? []
  const states = config.states ?? []

  const addReplyStyle = () => {
    onChange({ ...config, multiple_reply_style: [...replyStyles, ''] })
  }

  const removeReplyStyle = (index: number) => {
    onChange({
      ...config,
      multiple_reply_style: replyStyles.filter((_, i) => i !== index),
    })
  }

  const updateReplyStyle = (index: number, value: string) => {
    const newReplyStyles = [...replyStyles]
    newReplyStyles[index] = value
    onChange({ ...config, multiple_reply_style: newReplyStyles })
  }

  const addState = () => {
    onChange({ ...config, states: [...states, ''] })
  }

  const removeState = (index: number) => {
    onChange({
      ...config,
      states: states.filter((_, i) => i !== index),
    })
  }

  const updateState = (index: number, value: string) => {
    const newStates = [...states]
    newStates[index] = value
    onChange({ ...config, states: newStates })
  }

  return (
    <>
      <div className="space-y-4 sm:hidden">
        <div className="ios-group overflow-hidden">
          <MobileTextareaBlock
            icon={<Brain className="h-4 w-4" />}
            iconClassName="ios-symbol-purple"
            label="人格特质"
            description="120 字内"
            value={config.personality}
            onChange={(value) => onChange({ ...config, personality: value })}
            placeholder="描述人格特质和身份特征"
            rows={3}
          />
          <MobileTextareaBlock
            icon={<MessageCircle className="h-4 w-4" />}
            iconClassName="ios-symbol-blue"
            label="表达风格"
            value={config.reply_style}
            onChange={(value) => onChange({ ...config, reply_style: value })}
            placeholder="描述说话的表达风格和习惯"
            rows={3}
          />
        </div>

        <div className="ios-group overflow-hidden">
          <div className="ios-row">
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-teal">
                <WandSparkles className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium">可选表达风格</span>
            </span>
            <Button
              onClick={addReplyStyle}
              size="icon"
              variant="outline"
              className="h-9 w-9 rounded-full"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {replyStyles.length === 0 ? (
            <div className="ios-row min-h-12 py-3 text-[14px] text-muted-foreground">
              未配置可选表达风格
            </div>
          ) : (
            replyStyles.map((style, index) => (
              <div key={index} className="border-b border-border/70 px-4 py-3 last:border-b-0">
                <div className="flex items-start gap-2">
                  <Textarea
                    value={style}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                      updateReplyStyle(index, e.target.value)
                    }
                    placeholder="描述一种可随机替换的表达风格"
                    rows={2}
                    className="min-h-0 flex-1 resize-none border-0 bg-transparent px-0 py-0 text-[14px] leading-relaxed shadow-none focus-visible:ring-0"
                  />
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="icon" variant="outline" className={destructiveIconButtonClass}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>确认删除</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除这个可选表达风格吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeReplyStyle(index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
            ))
          )}
          <MobileProbabilityRow
            label="风格替换概率"
            description="范围 0.0-1.0"
            value={config.multiple_probability}
            onChange={(value) => onChange({ ...config, multiple_probability: parseFloat(value) })}
          />
        </div>

        <div className="ios-group overflow-hidden">
          <MobileTextareaBlock
            icon={<Sparkles className="h-4 w-4" />}
            iconClassName="ios-symbol-pink"
            label="说话规则"
            value={config.plan_style}
            onChange={(value) => onChange({ ...config, plan_style: value })}
            placeholder="当前实例的说话规则和行为风格"
            rows={5}
          />
        </div>

        <div className="ios-group overflow-hidden">
          <div className="ios-row">
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                <Sparkles className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium">人格状态</span>
            </span>
            <Button
              onClick={addState}
              size="icon"
              variant="outline"
              className="h-9 w-9 rounded-full"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {states.length === 0 ? (
            <div className="ios-row min-h-12 py-3 text-[14px] text-muted-foreground">
              未配置人格状态
            </div>
          ) : (
            states.map((state, index) => (
              <div key={index} className="border-b border-border/70 px-4 py-3 last:border-b-0">
                <div className="flex items-start gap-2">
                  <Textarea
                    value={state}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                      updateState(index, e.target.value)
                    }
                    placeholder="描述一个人格状态"
                    rows={2}
                    className="min-h-0 flex-1 resize-none border-0 bg-transparent px-0 py-0 text-[14px] leading-relaxed shadow-none focus-visible:ring-0"
                  />
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="icon" variant="outline" className={destructiveIconButtonClass}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>确认删除</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除这个人格状态吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeState(index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
            ))
          )}
          <MobileProbabilityRow
            label="状态替换概率"
            description="范围 0.0-1.0"
            value={config.state_probability}
            onChange={(value) => onChange({ ...config, state_probability: parseFloat(value) })}
          />
        </div>
      </div>

      <div className="ios-group hidden space-y-6 p-4 sm:block sm:p-6">
        <div>
          <h3 className="mb-4 text-lg font-semibold">人格设置</h3>

          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="personality">人格特质</Label>
              <Textarea
                id="personality"
                value={config.personality}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  onChange({ ...config, personality: e.target.value })
                }
                placeholder="描述人格特质和身份特征（建议120字以内）"
                rows={3}
              />
              <p className="text-xs text-muted-foreground">建议120字以内，描述人格特质和身份特征</p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="reply_style">表达风格</Label>
              <Textarea
                id="reply_style"
                value={config.reply_style}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  onChange({ ...config, reply_style: e.target.value })
                }
                placeholder="描述说话的表达风格和习惯"
                rows={3}
              />
            </div>

            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <Label>可选表达风格</Label>
                <Button onClick={addReplyStyle} size="sm" variant="outline">
                  <Plus className="mr-1 h-4 w-4" />
                  添加风格
                </Button>
              </div>
              <div className="space-y-2">
                {replyStyles.map((style, index) => (
                  <div key={index} className="flex gap-2">
                    <Textarea
                      value={style}
                      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                        updateReplyStyle(index, e.target.value)
                      }
                      placeholder="描述一种可随机替换的表达风格"
                      rows={2}
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
                            确定要删除这个可选表达风格吗？此操作无法撤销。
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>取消</AlertDialogCancel>
                          <AlertDialogAction onClick={() => removeReplyStyle(index)}>
                            删除
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                ))}
              </div>
              {replyStyles.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  未配置可选表达风格时，始终使用上方默认表达风格。
                </p>
              )}
            </div>

            <div className="grid gap-2">
              <Label htmlFor="multiple_probability">可选表达风格替换概率</Label>
              <Input
                id="multiple_probability"
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={config.multiple_probability}
                onChange={(e) =>
                  onChange({ ...config, multiple_probability: parseFloat(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">
                每次构建回复时，从可选表达风格中随机替换默认表达风格的概率（0.0-1.0）
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="plan_style">说话规则与行为风格</Label>
              <Textarea
                id="plan_style"
                value={config.plan_style}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  onChange({ ...config, plan_style: e.target.value })
                }
                placeholder="当前实例的说话规则和行为风格"
                rows={5}
              />
            </div>

            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <Label>状态列表（人格多样性）</Label>
                <Button onClick={addState} size="sm" variant="outline">
                  <Plus className="mr-1 h-4 w-4" />
                  添加状态
                </Button>
              </div>
              <div className="space-y-2">
                {states.map((state, index) => (
                  <div key={index} className="flex gap-2">
                    <Textarea
                      value={state}
                      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                        updateState(index, e.target.value)
                      }
                      placeholder="描述一个人格状态"
                      rows={2}
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
                            确定要删除这个人格状态吗？此操作无法撤销。
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>取消</AlertDialogCancel>
                          <AlertDialogAction onClick={() => removeState(index)}>
                            删除
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="state_probability">状态替换概率</Label>
              <Input
                id="state_probability"
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={config.state_probability}
                onChange={(e) =>
                  onChange({ ...config, state_probability: parseFloat(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">
                每次构建人格时替换 personality 的概率（0.0-1.0）
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  )
})
