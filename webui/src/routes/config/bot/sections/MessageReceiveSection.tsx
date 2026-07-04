import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plus, Trash2 } from 'lucide-react'
import type { MessageReceiveConfig } from '../types'

interface MessageReceiveSectionProps {
  config: MessageReceiveConfig
  onChange: (config: MessageReceiveConfig) => void
}

export const MessageReceiveSection = React.memo(function MessageReceiveSection({
  config,
  onChange,
}: MessageReceiveSectionProps) {
  const banWords = config.ban_words ?? []
  const banRegex = config.ban_msgs_regex ?? []

  const updateList = (field: 'ban_words' | 'ban_msgs_regex', index: number, value: string) => {
    const current = field === 'ban_words' ? banWords : banRegex
    const next = [...current]
    next[index] = value
    onChange({ ...config, [field]: next })
  }

  const addItem = (field: 'ban_words' | 'ban_msgs_regex') => {
    const current = field === 'ban_words' ? banWords : banRegex
    onChange({ ...config, [field]: [...current, ''] })
  }

  const removeItem = (field: 'ban_words' | 'ban_msgs_regex', index: number) => {
    const current = field === 'ban_words' ? banWords : banRegex
    onChange({ ...config, [field]: current.filter((_, i) => i !== index) })
  }

  const renderList = (
    title: string,
    description: string,
    field: 'ban_words' | 'ban_msgs_regex',
    values: string[],
    placeholder: string
  ) => (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <Label>{title}</Label>
          <p className="text-xs text-muted-foreground mt-1">{description}</p>
        </div>
        <Button onClick={() => addItem(field)} size="sm" variant="outline">
          <Plus className="h-4 w-4 mr-1" />
          添加
        </Button>
      </div>

      <div className="space-y-2">
        {values.map((value, index) => (
          <div key={index} className="flex gap-2">
            <Input
              value={value}
              onChange={(e) => updateList(field, index, e.target.value)}
              placeholder={placeholder}
              className={field === 'ban_msgs_regex' ? 'font-mono text-sm' : undefined}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => removeItem(field, index)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>

      {values.length === 0 && (
        <p className="text-xs text-muted-foreground">当前没有配置过滤项</p>
      )}
    </div>
  )

  return (
    <div className="rounded-lg border bg-card p-4 sm:p-6 space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-4">消息过滤</h3>
        <div className="space-y-4">
          {renderList('过滤词', '包含这些词的消息将不会被读取', 'ban_words', banWords, '输入过滤词')}
          {renderList(
            '过滤正则表达式',
            '匹配到这些正则表达式的原始消息将被过滤',
            'ban_msgs_regex',
            banRegex,
            '例如：https?://[^\\s]+'
          )}
        </div>
      </div>
    </div>
  )
})
