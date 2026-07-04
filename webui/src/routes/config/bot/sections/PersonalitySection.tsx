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
import { Plus, Trash2 } from 'lucide-react'
import type { PersonalityConfig } from '../types'

interface PersonalitySectionProps {
  config: PersonalityConfig
  onChange: (config: PersonalityConfig) => void
}

export const PersonalitySection = React.memo(function PersonalitySection({ config, onChange }: PersonalitySectionProps) {
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
    <div className="rounded-lg border bg-card p-4 sm:p-6 space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-4">人格设置</h3>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="personality">人格特质</Label>
            <Textarea
              id="personality"
              value={config.personality}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => onChange({ ...config, personality: e.target.value })}
              placeholder="描述人格特质和身份特征（建议120字以内）"
              rows={3}
            />
            <p className="text-xs text-muted-foreground">
              建议120字以内，描述人格特质和身份特征
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="reply_style">表达风格</Label>
            <Textarea
              id="reply_style"
              value={config.reply_style}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => onChange({ ...config, reply_style: e.target.value })}
              placeholder="描述说话的表达风格和习惯"
              rows={3}
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>可选表达风格</Label>
              <Button onClick={addReplyStyle} size="sm" variant="outline">
                <Plus className="h-4 w-4 mr-1" />
                添加风格
              </Button>
            </div>
            <div className="space-y-2">
              {replyStyles.map((style, index) => (
                <div key={index} className="flex gap-2">
                  <Textarea
                    value={style}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => updateReplyStyle(index, e.target.value)}
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
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => onChange({ ...config, plan_style: e.target.value })}
              placeholder="璃夜的说话规则和行为风格"
              rows={5}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="visual_style">识图规则</Label>
            <Textarea
              id="visual_style"
              value={config.visual_style}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => onChange({ ...config, visual_style: e.target.value })}
              placeholder="识图时的处理规则"
              rows={3}
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>状态列表（人格多样性）</Label>
              <Button onClick={addState} size="sm" variant="outline">
                <Plus className="h-4 w-4 mr-1" />
                添加状态
              </Button>
            </div>
            <div className="space-y-2">
              {states.map((state, index) => (
                <div key={index} className="flex gap-2">
                  <Textarea
                    value={state}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => updateState(index, e.target.value)}
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
  )
})
