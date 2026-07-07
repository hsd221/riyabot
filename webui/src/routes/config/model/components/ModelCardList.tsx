/**
 * 模型列表 - 移动端卡片视图
 */
import React from 'react'
import { Check, ChevronRight, Cpu, Trash2 } from 'lucide-react'
import type { ModelInfo } from '../types'
import { cn } from '@/lib/utils'

interface ModelCardListProps {
  /** 当前页显示的模型 (分页后的) */
  paginatedModels: ModelInfo[]
  /** 所有模型列表 (未分页) */
  allModels: ModelInfo[]
  /** 编辑模型回调 */
  onEdit: (model: ModelInfo, index: number) => void
  /** 删除模型回调 */
  onDelete: (index: number) => void
  /** 已选择模型索引 */
  selectedModels: Set<number>
  /** 切换模型选择 */
  onToggleSelection: (index: number) => void
  /** 检查模型是否被使用 */
  isModelUsed: (modelName: string) => boolean
  /** 搜索关键词 */
  searchQuery: string
}

export const ModelCardList = React.memo(function ModelCardList({
  paginatedModels,
  allModels,
  onEdit,
  onDelete,
  selectedModels,
  onToggleSelection,
  isModelUsed,
  searchQuery,
}: ModelCardListProps) {
  if (paginatedModels.length === 0) {
    return (
      <div className="ios-group ios-empty-state md:hidden">
        <span className="ios-empty-illustration">
          <Cpu className="h-7 w-7 text-primary" />
        </span>
        <span className="space-y-1.5">
          <span className="block text-[15px] font-semibold leading-5 text-foreground">
            {searchQuery ? '未找到匹配的模型' : '暂无模型配置'}
          </span>
          <span className="block text-[13px] leading-5 text-muted-foreground">
            {searchQuery ? '换个关键词再试试' : '添加模型后会显示在这里'}
          </span>
        </span>
      </div>
    )
  }

  return (
    <div className="ios-group overflow-hidden md:hidden">
      {paginatedModels.map((model, displayIndex) => {
        const actualIndex = allModels.findIndex((m) => m === model)
        const used = isModelUsed(model.name)
        const selected = selectedModels.has(actualIndex)
        const modelDetails = [
          model.api_provider,
          model.temperature != null ? `温度 ${model.temperature}` : '默认温度',
        ]

        return (
          <div
            key={displayIndex}
            className="relative grid min-h-[96px] w-full grid-cols-[36px_minmax(0,1fr)_36px] items-center gap-3 px-4 py-3 after:absolute after:bottom-0 after:left-16 after:right-0 after:h-px after:bg-border/55 last:after:hidden"
          >
            <button
              type="button"
              onClick={() => actualIndex >= 0 && onToggleSelection(actualIndex)}
              disabled={actualIndex < 0}
              className={cn(
                'ios-touch grid h-9 w-9 place-items-center rounded-full focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-50',
                selected && 'bg-primary/12 text-primary'
              )}
              aria-label={selected ? `取消选择 ${model.name}` : `选择 ${model.name}`}
              aria-pressed={selected}
            >
              <span
                className={cn(
                  'grid h-5 w-5 place-items-center rounded-[7px] border border-muted-foreground/35',
                  selected && 'border-primary bg-primary text-primary-foreground'
                )}
              >
                {selected && <Check className="h-3.5 w-3.5" />}
              </span>
            </button>

            <button
              type="button"
              onClick={() => actualIndex >= 0 && onEdit(model, actualIndex)}
              disabled={actualIndex < 0}
              className="ios-touch -mx-1 grid min-w-0 grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 rounded-[13px] px-1 py-1 text-left leading-normal focus-visible:bg-accent/70 focus-visible:ring-0 disabled:opacity-50"
            >
              <span className="ios-symbol ios-symbol-md ios-symbol-blue">
                <Cpu className="h-4 w-4" />
              </span>
              <span className="min-w-0 self-center">
                <span className="block truncate text-[16px] font-semibold leading-6">
                  {model.name}
                </span>
                <span
                  className="block truncate text-[13px] leading-5 text-muted-foreground"
                  title={model.model_identifier}
                >
                  {model.model_identifier}
                </span>
                <span className="mt-1 block truncate text-[12.5px] leading-[18px] text-muted-foreground/90">
                  {modelDetails.join(' · ')}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                <span className="rounded-full bg-secondary px-2 py-0.5">
                  <span
                    className={
                      used
                        ? 'text-[13px] font-medium leading-5 text-[rgb(36_138_61)] dark:text-[rgb(48_209_88)]'
                        : 'text-[13px] leading-5 text-muted-foreground'
                    }
                  >
                    {used ? '已使用' : '未使用'}
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 text-muted-foreground/70" />
              </span>
            </button>

            <button
              type="button"
              onClick={() => actualIndex >= 0 && onDelete(actualIndex)}
              disabled={actualIndex < 0}
              className="ios-touch text-destructive focus-visible:bg-destructive/10 grid h-9 w-9 place-items-center rounded-full focus-visible:ring-0 disabled:opacity-50"
              aria-label={`删除 ${model.name}`}
              title="删除模型"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        )
      })}
    </div>
  )
})
