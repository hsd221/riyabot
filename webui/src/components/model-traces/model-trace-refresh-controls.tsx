import { RefreshCw } from 'lucide-react'

import { Button } from '../ui/button'
import { Switch } from '../ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip'

const AUTO_REFRESH_ID = 'model-traces-auto-refresh'

interface ModelTraceRefreshControlsProps {
  autoRefresh: boolean
  loading: boolean
  onAutoRefreshChange: (checked: boolean) => void
  onRefresh: () => void
}

export function ModelTraceRefreshControls({
  autoRefresh,
  loading,
  onAutoRefreshChange,
  onRefresh,
}: ModelTraceRefreshControlsProps) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:flex">
      <div className="ios-group flex min-h-11 min-w-0 items-center justify-between gap-4 px-4 sm:min-w-[190px]">
        <label
          htmlFor={AUTO_REFRESH_ID}
          className="flex min-w-0 cursor-pointer items-center gap-2 text-sm font-medium"
        >
          <RefreshCw className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span className="truncate">自动刷新</span>
        </label>
        <Switch
          id={AUTO_REFRESH_ID}
          checked={autoRefresh}
          onCheckedChange={onAutoRefreshChange}
        />
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-11 w-11 shrink-0 rounded-full"
            onClick={onRefresh}
            disabled={loading}
            aria-label="刷新模型请求追踪"
          >
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>刷新模型请求追踪</TooltipContent>
      </Tooltip>
    </div>
  )
}
