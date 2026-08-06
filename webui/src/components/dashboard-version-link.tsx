import { ChevronRight, Download } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import type { UpdateChannel } from '@/lib/update-api'

type DashboardVersionLinkProps = {
  version: string
  updateAvailable: boolean
  channel?: UpdateChannel
}

export function DashboardVersionLink({
  version,
  updateAvailable,
  channel,
}: DashboardVersionLinkProps) {
  const channelLabel = channel === 'dev' ? '开发频道' : '正式版频道'
  const accessibleLabel = updateAvailable
    ? `当前版本 v${version}，${channelLabel}有更新，前往系统更新`
    : `当前版本 v${version}，前往系统更新`

  return (
    <Link
      to="/settings"
      search={{ tab: 'about' }}
      className="ios-row ios-touch min-h-12 py-3"
      aria-label={accessibleLabel}
    >
      <span className="text-[15px] text-muted-foreground">版本</span>
      <span className="flex min-w-0 max-w-[72%] items-center justify-end gap-2">
        {updateAvailable && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            有更新
          </span>
        )}
        <span className="truncate text-right text-[15px] font-medium">v{version}</span>
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/80" aria-hidden="true" />
      </span>
    </Link>
  )
}
