import { cn } from '@/lib/utils'

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'animate-[ios-shimmer_1.45s_ease-in-out_infinite] rounded-md bg-[linear-gradient(90deg,hsl(var(--muted)_/_0.62),hsl(var(--muted)_/_0.94),hsl(var(--muted)_/_0.62))] bg-[length:220%_100%]',
        className
      )}
      {...props}
    />
  )
}

function IosListSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('divide-y divide-border/45', className)} role="status" aria-label="加载中">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="ios-row min-h-[88px] justify-start gap-3 py-3">
          <Skeleton className="h-8 w-8 shrink-0 rounded-[10px]" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-4 w-2/5 rounded-full" />
            <Skeleton className="h-3.5 w-4/5 rounded-full" />
            <Skeleton className="h-3 w-1/3 rounded-full" />
          </div>
          <Skeleton className="hidden h-9 w-20 rounded-full sm:block" />
        </div>
      ))}
    </div>
  )
}

function IosGridSkeleton({ items = 12, className }: { items?: number; className?: string }) {
  return (
    <div
      className={cn(
        'grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 sm:p-4 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8',
        className
      )}
      role="status"
      aria-label="加载中"
    >
      {Array.from({ length: items }).map((_, index) => (
        <div
          key={index}
          className="overflow-hidden rounded-[16px] border border-black/[0.035] bg-white/[0.72] shadow-[0_1px_0_rgba(255,255,255,0.72)_inset,0_6px_18px_rgba(31,41,55,0.035)] backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.09]"
        >
          <Skeleton className="aspect-square w-full rounded-none" />
          <div className="space-y-2 border-t border-border/55 p-2">
            <Skeleton className="h-3 w-2/3 rounded-full" />
            <Skeleton className="h-3 w-1/2 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  )
}

export { Skeleton, IosListSkeleton, IosGridSkeleton }
