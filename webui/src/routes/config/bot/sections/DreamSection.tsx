import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Plus, Trash2 } from 'lucide-react'
import type { DreamConfig } from '../types'

interface DreamSectionProps {
  config: DreamConfig
  onChange: (config: DreamConfig) => void
}

export const DreamSection = React.memo(function DreamSection({ config, onChange }: DreamSectionProps) {
  const dreamTimeRanges = config.dream_time_ranges ?? []

  const addDreamTimeRange = () => {
    onChange({ ...config, dream_time_ranges: [...dreamTimeRanges, '23:00-10:00'] })
  }

  const updateDreamTimeRange = (index: number, value: string) => {
    const nextRanges = [...dreamTimeRanges]
    nextRanges[index] = value
    onChange({ ...config, dream_time_ranges: nextRanges })
  }

  const removeDreamTimeRange = (index: number) => {
    onChange({ ...config, dream_time_ranges: dreamTimeRanges.filter((_, i) => i !== index) })
  }

  return (
    <div className="rounded-lg border bg-card p-4 sm:p-6 space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-4">Dream 配置</h3>
        <div className="grid gap-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="interval_minutes">做梦间隔（分钟）</Label>
              <Input
                id="interval_minutes"
                type="number"
                min="1"
                value={config.interval_minutes}
                onChange={(e) => onChange({ ...config, interval_minutes: parseInt(e.target.value) })}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="max_iterations">最大轮次</Label>
              <Input
                id="max_iterations"
                type="number"
                min="1"
                value={config.max_iterations}
                onChange={(e) => onChange({ ...config, max_iterations: parseInt(e.target.value) })}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="first_delay_seconds">首次延迟（秒）</Label>
              <Input
                id="first_delay_seconds"
                type="number"
                min="0"
                value={config.first_delay_seconds}
                onChange={(e) => onChange({ ...config, first_delay_seconds: parseInt(e.target.value) })}
              />
            </div>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="dream_send">做梦结果推送目标</Label>
            <Input
              id="dream_send"
              value={config.dream_send}
              onChange={(e) => onChange({ ...config, dream_send: e.target.value })}
              placeholder="qq:123456"
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">为空时不推送，格式为 platform:user_id</p>
          </div>

          <div className="flex items-center space-x-2">
            <Switch
              id="dream_visible"
              checked={config.dream_visible}
              onCheckedChange={(checked) => onChange({ ...config, dream_visible: checked })}
            />
            <Label htmlFor="dream_visible" className="cursor-pointer">
              做梦结果写入聊天上下文
            </Label>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <div>
                <Label>允许做梦的时间段</Label>
                <p className="text-xs text-muted-foreground mt-1">
                  为空表示全天允许，支持跨夜区间
                </p>
              </div>
              <Button onClick={addDreamTimeRange} size="sm" variant="outline">
                <Plus className="h-4 w-4 mr-1" />
                添加
              </Button>
            </div>

            <div className="space-y-2">
              {dreamTimeRanges.map((range, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    value={range}
                    onChange={(e) => updateDreamTimeRange(index, e.target.value)}
                    placeholder="23:00-10:00"
                    className="font-mono text-sm"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => removeDreamTimeRange(index)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>

            {dreamTimeRanges.length === 0 && (
              <p className="text-xs text-muted-foreground">当前没有限制时间段</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
})
