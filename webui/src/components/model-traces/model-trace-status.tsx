import { AlertCircle, CheckCircle2, LoaderCircle } from 'lucide-react'
import { Badge } from '../ui/badge'
import { cn } from '../../lib/utils'
import type { ModelTraceStatus } from '../../types/model-trace'

const statusConfig = {
  running: {
    label: '请求中',
    icon: LoaderCircle,
    className:
      'border-[rgb(0_122_255_/_0.14)] bg-[rgb(0_122_255_/_0.1)] text-[#0066CC] dark:text-[#66B2FF]',
  },
  success: {
    label: '成功',
    icon: CheckCircle2,
    className:
      'border-[rgb(52_199_89_/_0.16)] bg-[rgb(52_199_89_/_0.11)] text-[#218739] dark:text-[#7EE894]',
  },
  error: {
    label: '失败',
    icon: AlertCircle,
    className:
      'border-[rgb(255_59_48_/_0.16)] bg-[rgb(255_59_48_/_0.11)] text-[#C9342B] dark:text-[#FF6961]',
  },
} satisfies Record<ModelTraceStatus, { label: string; icon: typeof AlertCircle; className: string }>

export function ModelTraceStatusBadge({ status }: { status: ModelTraceStatus }) {
  const config = statusConfig[status]
  const Icon = config.icon
  return (
    <Badge variant="outline" className={cn('gap-1.5 border', config.className)}>
      <Icon className={cn('h-3.5 w-3.5', status === 'running' && 'animate-spin')} />
      {config.label}
    </Badge>
  )
}
