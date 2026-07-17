import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plus, Trash2 } from 'lucide-react'
import type { ExperimentalConfig } from '../types'

interface ExperimentalSectionProps {
  config: ExperimentalConfig
  onChange: (config: ExperimentalConfig) => void
}

export const ExperimentalSection = React.memo(function ExperimentalSection({
  config,
  onChange,
}: ExperimentalSectionProps) {
  const chatPrompts = config.chat_prompts ?? []

  const addChatPrompt = () => {
    onChange({ ...config, chat_prompts: [...chatPrompts, ''] })
  }

  const updateChatPrompt = (index: number, value: string) => {
    const nextPrompts = [...chatPrompts]
    nextPrompts[index] = value
    onChange({ ...config, chat_prompts: nextPrompts })
  }

  const removeChatPrompt = (index: number) => {
    onChange({ ...config, chat_prompts: chatPrompts.filter((_, i) => i !== index) })
  }

  return (
    <div className="ios-group space-y-6 p-4 sm:p-6">
      <div>
        <h3 className="mb-4 text-lg font-semibold">实验性功能</h3>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <div>
                <Label>聊天额外 Prompt</Label>
                <p className="mt-1 text-xs text-muted-foreground">
                  格式：platform:id:type:prompt内容
                </p>
              </div>
              <Button onClick={addChatPrompt} size="sm" variant="outline">
                <Plus className="mr-1 h-4 w-4" />
                添加
              </Button>
            </div>

            <div className="space-y-2">
              {chatPrompts.map((prompt, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    value={prompt}
                    onChange={(e) => updateChatPrompt(index, e.target.value)}
                    placeholder="qq:114514:group:这是一个摄影群，你精通摄影知识"
                    className="font-mono text-sm"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => removeChatPrompt(index)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>

            {chatPrompts.length === 0 && (
              <p className="text-xs text-muted-foreground">当前没有配置额外 Prompt</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
})
