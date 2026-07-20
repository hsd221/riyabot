import { useCallback, useDeferredValue, useEffect, useState } from 'react'
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  ScanSearch,
  Search,
  X,
} from 'lucide-react'
import { ModelTraceDetailPanel } from '@/components/model-traces/model-trace-detail'
import { ModelTraceList } from '@/components/model-traces/model-trace-list'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fetchModelTraceDetail, fetchModelTraces } from '@/lib/api/model-trace-api'
import type {
  ModelTraceDetail,
  ModelTraceListResponse,
  ModelTraceStatus,
} from '@/types/model-trace'

const PAGE_SIZE = 30

function DetailSkeleton() {
  return (
    <div className="space-y-5 p-4 sm:p-5" aria-busy="true" aria-label="加载请求详情">
      <div className="flex items-start justify-between gap-4 border-b border-border/60 pb-4">
        <div className="space-y-2">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-64 max-w-full" />
        </div>
        <Skeleton className="h-9 w-20 rounded-full" />
      </div>
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-16 rounded-[8px]" />
        ))}
      </div>
      <Skeleton className="h-12 w-72 max-w-full" />
      <Skeleton className="h-[28rem] w-full rounded-[8px]" />
    </div>
  )
}

export function ModelTracesPage() {
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<'all' | ModelTraceStatus>('all')
  const [requestType, setRequestType] = useState('all')
  const [model, setModel] = useState('all')
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [list, setList] = useState<ModelTraceListResponse | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ModelTraceDetail | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoadingList(true)
    setListError(null)

    fetchModelTraces(
      {
        page,
        pageSize: PAGE_SIZE,
        status: status === 'all' ? undefined : status,
        requestType: requestType === 'all' ? undefined : requestType,
        model: model === 'all' ? undefined : model,
        search: deferredSearch,
      },
      controller.signal
    )
      .then((result) => {
        setList(result)
        setSelectedId((current) => {
          if (current && result.data.some((trace) => trace.id === current)) return current
          return result.data[0]?.id ?? null
        })
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setListError(caught instanceof Error ? caught.message : '无法获取模型请求追踪')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingList(false)
      })

    return () => controller.abort()
  }, [deferredSearch, model, page, refreshVersion, requestType, status])

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null)
      setDetailError(null)
      setLoadingDetail(false)
      return
    }
    const controller = new AbortController()
    setLoadingDetail(true)
    setDetailError(null)

    fetchModelTraceDetail(selectedId, controller.signal)
      .then(setDetail)
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setDetailError(caught instanceof Error ? caught.message : '无法获取请求详情')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingDetail(false)
      })

    return () => controller.abort()
  }, [selectedId, refreshVersion])

  const refresh = useCallback(() => setRefreshVersion((version) => version + 1), [])
  const resetPage = () => setPage(1)
  const totalItems = list?.pagination.total_items ?? 0
  const totalPages = list?.pagination.total_pages ?? 0

  return (
    <div className="ios-page h-full overflow-y-auto">
      <div className="ios-content">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <span className="ios-symbol ios-symbol-md ios-symbol-teal" aria-hidden="true">
                <ScanSearch className="h-5 w-5" />
              </span>
              <h1 className="ios-title">模型请求追踪</h1>
            </div>
            <p className="ios-subtitle">{totalItems.toLocaleString()} 条记录</p>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-11 w-11 shrink-0 rounded-[14px]"
                onClick={refresh}
                disabled={loadingList}
                aria-label="刷新模型请求追踪"
              >
                <RefreshCw className={loadingList ? 'animate-spin' : ''} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>刷新模型请求追踪</TooltipContent>
          </Tooltip>
        </header>

        <section className="grid gap-2 sm:grid-cols-2 xl:grid-cols-[minmax(16rem,1.4fr)_repeat(3,minmax(10rem,0.75fr))]">
          <div className="relative sm:col-span-2 xl:col-span-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              value={search}
              maxLength={200}
              onChange={(event) => {
                setSearch(event.target.value)
                resetPage()
              }}
              placeholder="搜索请求、模型或错误"
              aria-label="搜索模型请求追踪"
              className="pl-11 pr-11"
            />
            {search && (
              <button
                type="button"
                onClick={() => {
                  setSearch('')
                  resetPage()
                }}
                className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35"
                aria-label="清除搜索"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <Select
            value={status}
            onValueChange={(value: 'all' | ModelTraceStatus) => {
              setStatus(value)
              resetPage()
            }}
          >
            <SelectTrigger aria-label="按状态筛选">
              <SelectValue placeholder="全部状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="running">请求中</SelectItem>
              <SelectItem value="success">成功</SelectItem>
              <SelectItem value="error">失败</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={requestType}
            onValueChange={(value) => {
              setRequestType(value)
              resetPage()
            }}
          >
            <SelectTrigger aria-label="按请求类型筛选">
              <SelectValue placeholder="全部请求类型" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部请求类型</SelectItem>
              {list?.filter_options.request_types.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={model}
            onValueChange={(value) => {
              setModel(value)
              resetPage()
            }}
          >
            <SelectTrigger aria-label="按模型筛选">
              <SelectValue placeholder="全部模型" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部模型</SelectItem>
              {list?.filter_options.models.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </section>

        {listError && (
          <div className="border-destructive/20 bg-destructive/[0.08] text-destructive flex items-center gap-3 rounded-[8px] border px-4 py-3 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="min-w-0 break-words">{listError}</span>
          </div>
        )}

        <div className="ios-card grid min-h-[44rem] overflow-hidden lg:h-[calc(100vh-18rem)] lg:min-h-[36rem] lg:grid-cols-[minmax(20rem,24rem)_minmax(0,1fr)]">
          <section
            className="min-w-0 border-b border-border/60 lg:border-b-0 lg:border-r"
            aria-label="请求记录"
          >
            <div className="flex h-14 items-center justify-between border-b border-border/60 px-4">
              <div>
                <h2 className="text-[15px] font-semibold">请求记录</h2>
                <p className="text-[11px] leading-4 text-muted-foreground">
                  第 {totalPages === 0 ? 0 : page} / {totalPages} 页
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={loadingList || page <= 1}
                  aria-label="上一页"
                >
                  <ChevronLeft />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9"
                  onClick={() => setPage((current) => current + 1)}
                  disabled={loadingList || totalPages === 0 || page >= totalPages}
                  aria-label="下一页"
                >
                  <ChevronRight />
                </Button>
              </div>
            </div>
            <ScrollArea className="h-[32rem] lg:h-[calc(100%-3.5rem)]">
              <ModelTraceList
                traces={list?.data ?? []}
                selectedId={selectedId}
                loading={loadingList && !list}
                onSelect={setSelectedId}
              />
            </ScrollArea>
          </section>

          <div className="min-w-0 lg:overflow-y-auto">
            {loadingDetail ? (
              <DetailSkeleton />
            ) : detailError ? (
              <div className="flex min-h-[36rem] flex-col items-center justify-center gap-3 px-6 text-center">
                <span className="ios-symbol ios-symbol-md ios-symbol-red" aria-hidden="true">
                  <AlertCircle className="h-5 w-5" />
                </span>
                <div>
                  <p className="text-[16px] font-semibold">详情加载失败</p>
                  <p className="mt-1 max-w-md text-[13px] leading-5 text-muted-foreground">
                    {detailError}
                  </p>
                </div>
              </div>
            ) : detail ? (
              <ModelTraceDetailPanel detail={detail} />
            ) : (
              <div className="flex min-h-[36rem] flex-col items-center justify-center gap-3 px-6 text-center">
                <span className="ios-symbol ios-symbol-md ios-symbol-gray" aria-hidden="true">
                  <ScanSearch className="h-5 w-5" />
                </span>
                <p className="text-[15px] font-medium text-muted-foreground">未选择请求记录</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
