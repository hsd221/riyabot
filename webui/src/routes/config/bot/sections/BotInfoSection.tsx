import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import { AtSign, Bot, Plus, Smartphone, Trash2, UserRound } from 'lucide-react'
import type { BotConfig } from '../types'

const destructiveIconButtonClass =
  'h-11 w-11 shrink-0 rounded-full border-[rgb(255_59_48_/_0.18)] bg-[rgb(255_59_48_/_0.08)] text-[rgb(215_0_21)] hover:bg-[rgb(255_59_48_/_0.12)] hover:text-[rgb(174_37_31)] dark:border-[rgb(255_69_58_/_0.18)] dark:bg-[rgb(255_69_58_/_0.1)] dark:text-[rgb(255_105_97)]'

interface BotInfoSectionProps {
  config: BotConfig
  onChange: (config: BotConfig) => void
}

export const BotInfoSection = React.memo(function BotInfoSection({
  config,
  onChange,
}: BotInfoSectionProps) {
  const addPlatform = () => {
    onChange({ ...config, platforms: [...config.platforms, ''] })
  }

  const removePlatform = (index: number) => {
    onChange({
      ...config,
      platforms: config.platforms.filter((_, i) => i !== index),
    })
  }

  const updatePlatform = (index: number, value: string) => {
    const newPlatforms = [...config.platforms]
    newPlatforms[index] = value
    onChange({ ...config, platforms: newPlatforms })
  }

  const addAlias = () => {
    onChange({ ...config, alias_names: [...config.alias_names, ''] })
  }

  const removeAlias = (index: number) => {
    onChange({
      ...config,
      alias_names: config.alias_names.filter((_, i) => i !== index),
    })
  }

  const updateAlias = (index: number, value: string) => {
    const newAliases = [...config.alias_names]
    newAliases[index] = value
    onChange({ ...config, alias_names: newAliases })
  }

  return (
    <>
      <div className="space-y-5 sm:max-w-3xl">
        <div className="ios-group overflow-hidden">
          <div className="ios-row min-h-[68px]">
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-blue">
                <Smartphone className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium">平台</span>
            </span>
            <Input
              value={config.platform}
              onChange={(e) => onChange({ ...config, platform: e.target.value })}
              placeholder="qq"
              className="h-11 min-w-0 max-w-[56%] text-right"
            />
          </div>
          <div className="ios-row min-h-[68px]">
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-green">
                <AtSign className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium">QQ账号</span>
            </span>
            <Input
              value={config.qq_account}
              onChange={(e) => onChange({ ...config, qq_account: e.target.value })}
              placeholder="123456789"
              className="h-11 min-w-0 max-w-[56%] text-right"
            />
          </div>
          <div className="ios-row min-h-[68px]">
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-purple">
                <Bot className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium">昵称</span>
            </span>
            <Input
              value={config.nickname}
              onChange={(e) => onChange({ ...config, nickname: e.target.value })}
              placeholder="当前实例"
              className="h-11 min-w-0 max-w-[56%] text-right"
            />
          </div>
        </div>

        <div className="ios-group overflow-hidden">
          <div className="ios-row">
            <span className="text-[15px] font-medium">其他平台账号</span>
            <Button
              onClick={addPlatform}
              size="icon"
              variant="outline"
              className="h-11 w-11 rounded-full"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {config.platforms.length === 0 ? (
            <div className="ios-row min-h-12 py-3 text-[14px] text-muted-foreground">
              暂无其他平台账号
            </div>
          ) : (
            config.platforms.map((platform, index) => (
              <div key={index} className="ios-row min-h-[68px] py-3">
                <Input
                  value={platform}
                  onChange={(e) => updatePlatform(index, e.target.value)}
                  placeholder="wx:114514"
                  className="h-11 min-w-0"
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
                        确定要删除平台账号 "{platform || '(空)'}" 吗？此操作无法撤销。
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction onClick={() => removePlatform(index)}>
                        删除
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ))
          )}
        </div>

        <div className="ios-group overflow-hidden">
          <div className="ios-row">
            <span className="flex min-w-0 items-center gap-3">
              <span className="ios-symbol ios-symbol-sm ios-symbol-orange">
                <UserRound className="h-4 w-4" />
              </span>
              <span className="text-[15px] font-medium">别名</span>
            </span>
            <Button
              onClick={addAlias}
              size="icon"
              variant="outline"
              className="h-11 w-11 rounded-full"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {config.alias_names.length === 0 ? (
            <div className="ios-row min-h-12 py-3 text-[14px] text-muted-foreground">暂无别名</div>
          ) : (
            config.alias_names.map((alias, index) => (
              <div key={index} className="ios-row min-h-[68px] py-3">
                <Input
                  value={alias}
                  onChange={(e) => updateAlias(index, e.target.value)}
                  placeholder="小助手"
                  className="h-11 min-w-0"
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
                        确定要删除别名 "{alias || '(空)'}" 吗？此操作无法撤销。
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction onClick={() => removeAlias(index)}>删除</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="hidden">
        <h3 className="mb-4 text-lg font-semibold">基本信息</h3>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="platform">平台</Label>
            <Input
              id="platform"
              value={config.platform}
              onChange={(e) => onChange({ ...config, platform: e.target.value })}
              placeholder="qq"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="qq_account">QQ账号</Label>
            <Input
              id="qq_account"
              value={config.qq_account}
              onChange={(e) => onChange({ ...config, qq_account: e.target.value })}
              placeholder="123456789"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="nickname">昵称</Label>
            <Input
              id="nickname"
              value={config.nickname}
              onChange={(e) => onChange({ ...config, nickname: e.target.value })}
              placeholder="当前实例"
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>其他平台账号</Label>
              <Button onClick={addPlatform} size="sm" variant="outline">
                <Plus className="mr-1 h-4 w-4" />
                添加
              </Button>
            </div>
            <div className="space-y-2">
              {config.platforms.map((platform, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    value={platform}
                    onChange={(e) => updatePlatform(index, e.target.value)}
                    placeholder="wx:114514"
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
                          确定要删除平台账号 "{platform || '(空)'}" 吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removePlatform(index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              ))}
              {config.platforms.length === 0 && (
                <p className="text-sm text-muted-foreground">暂无其他平台账号</p>
              )}
            </div>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>别名</Label>
              <Button onClick={addAlias} size="sm" variant="outline">
                <Plus className="mr-1 h-4 w-4" />
                添加
              </Button>
            </div>
            <div className="space-y-2">
              {config.alias_names.map((alias, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    value={alias}
                    onChange={(e) => updateAlias(index, e.target.value)}
                    placeholder="小助手"
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
                          确定要删除别名 "{alias || '(空)'}" 吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeAlias(index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              ))}
              {config.alias_names.length === 0 && (
                <p className="text-sm text-muted-foreground">暂无别名</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
})
