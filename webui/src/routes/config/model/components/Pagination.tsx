/**
 * 模型列表分页组件
 */
import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { PAGE_SIZE_OPTIONS } from '../constants'

interface PaginationProps {
  page: number
  pageSize: number
  totalItems: number
  jumpToPage: string
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  onJumpToPageChange: (value: string) => void
  onJumpToPage: () => void
  onSelectionClear?: () => void
}

export const Pagination = React.memo(function Pagination({
  page,
  pageSize,
  totalItems,
  jumpToPage,
  onPageChange,
  onPageSizeChange,
  onJumpToPageChange,
  onJumpToPage,
  onSelectionClear,
}: PaginationProps) {
  const totalPages = Math.ceil(totalItems / pageSize)

  const handlePageSizeChange = (value: string) => {
    onPageSizeChange(parseInt(value))
    onPageChange(1)
    onSelectionClear?.()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      onJumpToPage()
    }
  }

  if (totalItems === 0) return null

  return (
    <div className="mt-5 space-y-3">
      <div className="ios-group flex items-center justify-between gap-3 px-4 py-3 sm:hidden">
        <div className="min-w-0">
          <p className="text-[15px] font-medium">
            第 {page} / {totalPages} 页
          </p>
          <p className="mt-1 truncate text-[13px] leading-5 text-muted-foreground">
            显示 {(page - 1) * pageSize + 1} 到 {Math.min(page * pageSize, totalItems)} 条，共{' '}
            {totalItems} 条
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page === 1}
            className="h-11 w-11 rounded-full"
            aria-label="上一页"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="h-11 w-11 rounded-full"
            aria-label="下一页"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <div className="ios-group hidden items-center justify-between gap-4 px-5 py-3 sm:flex">
        <div className="flex min-w-0 items-center gap-2">
          <Label htmlFor="page-size-model" className="whitespace-nowrap text-sm">
            每页显示
          </Label>
          <Select value={pageSize.toString()} onValueChange={handlePageSizeChange}>
            <SelectTrigger id="page-size-model" className="h-11 w-20">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((size) => (
                <SelectItem key={size} value={size.toString()}>
                  {size}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-sm text-muted-foreground">
            显示 {(page - 1) * pageSize + 1} 到 {Math.min(page * pageSize, totalItems)} 条，共{' '}
            {totalItems} 条
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(1)}
            disabled={page === 1}
            className="hidden h-11 w-11 rounded-full px-0 sm:flex"
          >
            <ChevronsLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page === 1}
          >
            <ChevronLeft className="h-4 w-4 sm:mr-1" />
            <span className="hidden sm:inline">上一页</span>
          </Button>
          <div className="flex min-w-0 items-center gap-2">
            <Input
              type="number"
              value={jumpToPage}
              onChange={(e) => onJumpToPageChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={page.toString()}
              className="h-11 w-20 rounded-full border-0 bg-muted/70 text-center shadow-none focus-visible:ring-0"
              min={1}
              max={totalPages}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={onJumpToPage}
              disabled={!jumpToPage}
              className="h-11 rounded-full px-4"
            >
              跳转
            </Button>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
          >
            <span className="hidden sm:inline">下一页</span>
            <ChevronRight className="h-4 w-4 sm:ml-1" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(totalPages)}
            disabled={page >= totalPages}
            className="hidden h-11 w-11 rounded-full px-0 sm:flex"
          >
            <ChevronsRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
})
