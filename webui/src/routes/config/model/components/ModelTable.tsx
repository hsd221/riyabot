/**
 * 模型列表 - 桌面端表格视图
 */
import React from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Check, Cpu, Pencil, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ModelInfo } from '../types'

interface ModelTableProps {
  /** 当前页显示的模型 (分页后的) */
  paginatedModels: ModelInfo[]
  /** 所有模型列表 (未分页) */
  allModels: ModelInfo[]
  /** 过滤后的模型列表 */
  filteredModels: ModelInfo[]
  /** 已选中的模型索引集合 */
  selectedModels: Set<number>
  /** 编辑模型回调 */
  onEdit: (model: ModelInfo, index: number) => void
  /** 删除模型回调 */
  onDelete: (index: number) => void
  /** 切换选中状态回调 */
  onToggleSelection: (index: number) => void
  /** 切换全选回调 */
  onToggleSelectAll: () => void
  /** 检查模型是否被使用 */
  isModelUsed: (modelName: string) => boolean
  /** 搜索关键词 */
  searchQuery: string
}

export const ModelTable = React.memo(function ModelTable({
  paginatedModels,
  allModels,
  filteredModels,
  selectedModels,
  onEdit,
  onDelete,
  onToggleSelection,
  onToggleSelectAll,
  isModelUsed,
  searchQuery,
}: ModelTableProps) {
  const allSelected = selectedModels.size === filteredModels.length && filteredModels.length > 0

  return (
    <div className="ios-group hidden overflow-hidden md:block">
      {filteredModels.length > 0 && (
        <div className="flex min-h-12 items-center justify-between gap-4 border-b border-border/45 px-5 text-[13px] leading-5 text-muted-foreground">
          <button
            type="button"
            className="ios-touch flex min-h-11 items-center gap-2 rounded-full pr-3 text-left focus-visible:bg-accent/70 focus-visible:ring-0"
            onClick={onToggleSelectAll}
            aria-label="选择全部模型"
            aria-pressed={allSelected}
          >
            <span
              className={cn(
                'grid h-6 w-6 place-items-center rounded-[8px] border border-muted-foreground/35',
                allSelected && 'border-primary bg-primary text-primary-foreground'
              )}
            >
              {allSelected && <Check className="h-4 w-4" strokeWidth={3} />}
            </span>
            <span>选择全部</span>
          </button>
          <span>{filteredModels.length} 个模型</span>
        </div>
      )}
      {paginatedModels.length === 0 ? (
        <div className="ios-empty-state">
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
      ) : (
        paginatedModels.map((model, displayIndex) => {
          const actualIndex = allModels.findIndex((m) => m === model)
          const used = isModelUsed(model.name)
          return (
            <div
              key={displayIndex}
              className="ios-touch flex min-h-[78px] items-center gap-4 border-b border-border/45 px-5 py-3 last:border-b-0 hover:bg-[rgb(120_120_128_/_0.06)]"
            >
              <button
                type="button"
                className="ios-touch grid h-11 w-11 shrink-0 place-items-center rounded-full focus-visible:bg-accent/70 focus-visible:ring-0"
                onClick={() => onToggleSelection(actualIndex)}
                aria-label={`选择模型 ${model.name}`}
                aria-pressed={selectedModels.has(actualIndex)}
              >
                <span
                  className={cn(
                    'grid h-6 w-6 place-items-center rounded-[8px] border border-muted-foreground/35',
                    selectedModels.has(actualIndex) &&
                      'border-primary bg-primary text-primary-foreground'
                  )}
                >
                  {selectedModels.has(actualIndex) && <Check className="h-4 w-4" strokeWidth={3} />}
                </span>
              </button>
              <span className="ios-symbol ios-symbol-md ios-symbol-blue">
                <Cpu className="h-4 w-4" />
              </span>
              <button
                type="button"
                onClick={() => onEdit(model, actualIndex)}
                className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35"
              >
                <span className="block truncate text-[15px] font-semibold leading-6 text-foreground">
                  {model.name}
                </span>
                <span
                  className="mt-0.5 block truncate text-[13px] leading-5 text-muted-foreground"
                  title={model.model_identifier}
                >
                  {model.model_identifier}
                </span>
                <span className="mt-1 block truncate text-[12.5px] leading-[18px] text-muted-foreground/90">
                  {model.api_provider} ·{' '}
                  {model.temperature != null ? `温度 ${model.temperature}` : '默认温度'} · 输入 ¥
                  {model.price_in}/M · 输出 ¥{model.price_out}/M
                </span>
              </button>
              <div className="flex w-24 shrink-0 justify-end lg:w-28">
                <Badge
                  variant="secondary"
                  className={
                    used
                      ? 'border-0 bg-[rgb(52_199_89_/_0.11)] text-[rgb(36_138_61)] shadow-none dark:text-[rgb(48_209_88)]'
                      : 'border-0 bg-secondary/80 text-muted-foreground shadow-none'
                  }
                >
                  {used ? '已使用' : '未使用'}
                </Badge>
              </div>
              <div className="flex w-28 shrink-0 justify-end gap-2 lg:w-32">
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => onEdit(model, actualIndex)}
                  className="h-11 w-11 rounded-full"
                  aria-label={`编辑模型 ${model.name}`}
                  title="编辑"
                >
                  <Pencil className="h-4 w-4" strokeWidth={2} fill="none" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onDelete(actualIndex)}
                  className="h-11 w-11 rounded-full text-[rgb(215_0_21)] hover:bg-[rgb(255_59_48_/_0.08)] hover:text-[rgb(174_37_31)] dark:text-[rgb(255_105_97)] dark:hover:bg-[rgb(255_69_58_/_0.12)]"
                  aria-label={`删除模型 ${model.name}`}
                  title="删除"
                >
                  <Trash2 className="h-4 w-4" strokeWidth={2} fill="none" />
                </Button>
              </div>
            </div>
          )
        })
      )}
    </div>
  )
})
