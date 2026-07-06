/**
 * 模型列表 - 移动端卡片视图
 */
import React from 'react'
import { ChevronRight, Cpu } from 'lucide-react'
import type { ModelInfo } from '../types'

interface ModelCardListProps {
  /** 当前页显示的模型 (分页后的) */
  paginatedModels: ModelInfo[]
  /** 所有模型列表 (未分页) */
  allModels: ModelInfo[]
  /** 编辑模型回调 */
  onEdit: (model: ModelInfo, index: number) => void
  /** 检查模型是否被使用 */
  isModelUsed: (modelName: string) => boolean
  /** 搜索关键词 */
  searchQuery: string
}

export const ModelCardList = React.memo(function ModelCardList({
  paginatedModels,
  allModels,
  onEdit,
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
        const modelDetails = [
          model.api_provider,
          model.temperature != null ? `温度 ${model.temperature}` : '默认温度',
        ]

        return (
          <button
            key={displayIndex}
            type="button"
            onClick={() => onEdit(model, actualIndex)}
            className="ios-touch relative grid min-h-[92px] w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left leading-normal after:absolute after:bottom-0 after:left-16 after:right-0 after:h-px after:bg-border/55 last:after:hidden focus-visible:bg-accent/70 focus-visible:ring-0"
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
        )
      })}
    </div>
  )
})
