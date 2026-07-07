import React from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
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
import type { BehaviorConfig } from '../types'

type BehaviorRule = [string, string, string]

interface BehaviorSectionProps {
  config: BehaviorConfig
  onChange: (config: BehaviorConfig) => void
}

function normalizeRule(rule: BehaviorRule): BehaviorRule {
  return [rule[0] ?? '', rule[1] ?? 'enable', rule[2] ?? 'enable']
}

export const BehaviorSection = React.memo(function BehaviorSection({
  config,
  onChange,
}: BehaviorSectionProps) {
  const learningList = (config.learning_list ?? []).map(normalizeRule)
  const behaviorGroups = config.behavior_groups ?? []

  const addLearningRule = () => {
    onChange({
      ...config,
      learning_list: [...learningList, ['', 'enable', 'enable']],
    })
  }

  const removeLearningRule = (index: number) => {
    onChange({
      ...config,
      learning_list: learningList.filter((_, itemIndex) => itemIndex !== index),
    })
  }

  const updateLearningRule = (index: number, field: 0 | 1 | 2, value: string) => {
    const next = learningList.map((rule) => [...rule] as BehaviorRule)
    next[index][field] = value
    onChange({
      ...config,
      learning_list: next,
    })
  }

  const addBehaviorGroup = () => {
    onChange({
      ...config,
      behavior_groups: [...behaviorGroups, []],
    })
  }

  const removeBehaviorGroup = (index: number) => {
    onChange({
      ...config,
      behavior_groups: behaviorGroups.filter((_, itemIndex) => itemIndex !== index),
    })
  }

  const addGroupMember = (groupIndex: number) => {
    const next = behaviorGroups.map((group) => [...group])
    next[groupIndex] = [...next[groupIndex], '']
    onChange({
      ...config,
      behavior_groups: next,
    })
  }

  const updateGroupMember = (groupIndex: number, memberIndex: number, value: string) => {
    const next = behaviorGroups.map((group) => [...group])
    next[groupIndex][memberIndex] = value
    onChange({
      ...config,
      behavior_groups: next,
    })
  }

  const removeGroupMember = (groupIndex: number, memberIndex: number) => {
    const next = behaviorGroups.map((group) => [...group])
    next[groupIndex] = next[groupIndex].filter((_, itemIndex) => itemIndex !== memberIndex)
    onChange({
      ...config,
      behavior_groups: next,
    })
  }

  return (
    <div className="space-y-6">
      <div className="ios-group space-y-6 p-4 sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold">行为学习规则</h3>
            <p className="mt-1 text-sm text-muted-foreground">配置各聊天流的行为学习和使用开关</p>
          </div>
          <Button onClick={addLearningRule} size="sm" variant="outline">
            <Plus className="mr-1 h-4 w-4" />
            添加规则
          </Button>
        </div>

        <div className="space-y-4">
          {learningList.map((rule, index) => {
            const isGlobal = rule[0] === ''
            const hasGlobalConfig = learningList.some((item, itemIndex) => itemIndex !== index && item[0] === '')
            const parts = rule[0].split(':')
            const platform = parts[0] || 'qq'
            const chatId = parts[1] || ''
            const chatType = parts[2] || 'group'

            return (
              <div
                key={index}
                className="space-y-4 rounded-[16px] border border-border/45 bg-muted/35 p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">
                    规则 {index + 1} {isGlobal && '（全局配置）'}
                  </span>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="icon" variant="ghost">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>确认删除</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除行为学习规则 {index + 1} 吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeLearningRule(index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>

                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label className="text-xs font-medium">配置类型</Label>
                    <Select
                      value={isGlobal ? 'global' : 'specific'}
                      onValueChange={(value) => {
                        updateLearningRule(index, 0, value === 'global' ? '' : 'qq::group')
                      }}
                      disabled={hasGlobalConfig && !isGlobal}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="global">全局配置</SelectItem>
                        <SelectItem value="specific" disabled={hasGlobalConfig && !isGlobal}>
                          详细配置
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {!isGlobal && (
                    <div className="grid gap-4 rounded-[14px] bg-muted/45 p-3 sm:grid-cols-3 sm:p-4">
                      <div className="grid gap-2">
                        <Label className="text-xs font-medium">平台</Label>
                        <Select
                          value={platform}
                          onValueChange={(value) =>
                            updateLearningRule(index, 0, `${value}:${chatId}:${chatType}`)
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="qq">QQ</SelectItem>
                            <SelectItem value="wx">微信</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-2">
                        <Label className="text-xs font-medium">聊天 ID</Label>
                        <Input
                          value={chatId}
                          onChange={(event) =>
                            updateLearningRule(index, 0, `${platform}:${event.target.value}:${chatType}`)
                          }
                          placeholder="群 ID 或用户 ID"
                          className="font-mono text-sm"
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label className="text-xs font-medium">类型</Label>
                        <Select
                          value={chatType}
                          onValueChange={(value) =>
                            updateLearningRule(index, 0, `${platform}:${chatId}:${value}`)
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="group">群组（group）</SelectItem>
                            <SelectItem value="private">私聊（private）</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  )}

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="flex items-center justify-between gap-4 rounded-[14px] bg-muted/45 p-3">
                      <div>
                        <Label className="text-xs font-medium">使用行为参考</Label>
                        <p className="mt-1 text-xs text-muted-foreground">允许回复时引用已学到的行为模式</p>
                      </div>
                      <Switch
                        checked={rule[1] === 'enable'}
                        onCheckedChange={(checked) =>
                          updateLearningRule(index, 1, checked ? 'enable' : 'disable')
                        }
                      />
                    </div>
                    <div className="flex items-center justify-between gap-4 rounded-[14px] bg-muted/45 p-3">
                      <div>
                        <Label className="text-xs font-medium">学习行为模式</Label>
                        <p className="mt-1 text-xs text-muted-foreground">允许从聊天片段抽取行为模式</p>
                      </div>
                      <Switch
                        checked={rule[2] === 'enable'}
                        onCheckedChange={(checked) =>
                          updateLearningRule(index, 2, checked ? 'enable' : 'disable')
                        }
                      />
                    </div>
                  </div>
                </div>
              </div>
            )
          })}

          {learningList.length === 0 && (
            <div className="py-8 text-center text-muted-foreground">暂无行为学习规则</div>
          )}
        </div>
      </div>

      <div className="ios-group space-y-6 p-4 sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold">行为共享组</h3>
            <p className="mt-1 text-sm text-muted-foreground">同组聊天流会共享可参考的行为模式</p>
          </div>
          <Button onClick={addBehaviorGroup} size="sm" variant="outline">
            <Plus className="mr-1 h-4 w-4" />
            添加组
          </Button>
        </div>

        <div className="space-y-4">
          {behaviorGroups.map((group, groupIndex) => (
            <div
              key={groupIndex}
              className="space-y-3 rounded-[16px] border border-border/45 bg-muted/35 p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium">共享组 {groupIndex + 1}</span>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => addGroupMember(groupIndex)}>
                    <Plus className="mr-1 h-4 w-4" />
                    成员
                  </Button>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="icon" variant="ghost">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>确认删除</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除行为共享组 {groupIndex + 1} 吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeBehaviorGroup(groupIndex)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>

              <div className="space-y-2">
                {group.map((member, memberIndex) => (
                  <div key={memberIndex} className="flex gap-2">
                    <Input
                      value={member}
                      onChange={(event) =>
                        updateGroupMember(groupIndex, memberIndex, event.target.value)
                      }
                      placeholder='输入 "*" 或 "qq:123456:group"'
                      className="font-mono text-sm"
                    />
                    <Button
                      size="icon"
                      variant="outline"
                      onClick={() => removeGroupMember(groupIndex, memberIndex)}
                      title="删除成员"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
                {group.length === 0 && (
                  <div className="rounded-[14px] bg-muted/45 py-6 text-center text-sm text-muted-foreground">
                    暂无成员
                  </div>
                )}
              </div>
            </div>
          ))}

          {behaviorGroups.length === 0 && (
            <div className="py-8 text-center text-muted-foreground">暂无行为共享组</div>
          )}
        </div>
      </div>
    </div>
  )
})
