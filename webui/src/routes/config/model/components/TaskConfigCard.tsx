/**
 * 任务配置卡片组件
 */
import React from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { MultiSelect } from '@/components/ui/multi-select'
import type { TaskConfig } from '../types'

interface TaskConfigCardProps {
  title: string
  description: string
  taskConfig: TaskConfig | undefined
  modelNames: string[]
  onChange: (field: keyof TaskConfig, value: string[] | number) => void
  hideTemperature?: boolean
  hideMaxTokens?: boolean
  dataTour?: string
}

export const TaskConfigCard = React.memo(function TaskConfigCard({
  title,
  description,
  taskConfig,
  modelNames,
  onChange,
  hideTemperature = false,
  hideMaxTokens = false,
  dataTour,
}: TaskConfigCardProps) {
  const handleModelChange = (values: string[]) => {
    onChange('model_list', values)
  }

  return (
    <div className="ios-card space-y-5 p-5 sm:p-6">
      <div>
        <h4 className="text-base font-semibold sm:text-lg">{title}</h4>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{description}</p>
      </div>

      <div className="grid gap-5">
        {/* 模型列表 */}
        <div className="grid gap-2" data-tour={dataTour}>
          <Label>模型列表</Label>
          <MultiSelect
            options={modelNames.map((name) => ({ label: name, value: name }))}
            selected={taskConfig?.model_list || []}
            onChange={handleModelChange}
            placeholder="选择模型..."
            emptyText="暂无可用模型"
          />
        </div>

        {/* 温度和最大 Token */}
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {!hideTemperature && (
            <div className="grid gap-3">
              <div className="flex items-center justify-between">
                <Label>温度</Label>
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={taskConfig?.temperature ?? 0.3}
                  onChange={(e) => {
                    const value = parseFloat(e.target.value)
                    if (!isNaN(value) && value >= 0 && value <= 1) {
                      onChange('temperature', value)
                    }
                  }}
                  className="h-11 w-24 rounded-2xl text-center text-base"
                />
              </div>
              <Slider
                value={[taskConfig?.temperature ?? 0.3]}
                onValueChange={(values) => onChange('temperature', values[0])}
                min={0}
                max={1}
                step={0.1}
                className="w-full"
              />
            </div>
          )}

          {!hideMaxTokens && (
            <div className="grid gap-2.5">
              <Label>最大 Token</Label>
              <Input
                type="number"
                step="1"
                min="1"
                value={taskConfig?.max_tokens ?? 1024}
                onChange={(e) => onChange('max_tokens', parseInt(e.target.value))}
              />
            </div>
          )}
        </div>

        {/* 慢请求阈值 */}
        <div className="grid gap-2.5">
          <div className="flex items-center justify-between">
            <Label>慢请求阈值 (秒)</Label>
            <span className="text-xs text-muted-foreground">超时警告</span>
          </div>
          <Input
            type="number"
            step="1"
            min="1"
            value={taskConfig?.slow_threshold ?? 15}
            onChange={(e) => {
              const value = parseInt(e.target.value)
              if (!isNaN(value) && value >= 1) {
                onChange('slow_threshold', value)
              }
            }}
            placeholder="15"
          />
          <p className="text-xs text-muted-foreground">
            模型响应时间超过此阈值将输出警告日志
          </p>
        </div>
      </div>
    </div>
  )
})
