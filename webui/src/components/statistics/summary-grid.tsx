import {
  Activity,
  Clock,
  Database,
  DollarSign,
  Gauge,
  MessageSquare,
  TrendingUp,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { StatisticsSummary } from '@/types/statistics'
import {
  formatCompactCurrency,
  formatCompactNumber,
  formatCurrency,
  formatDuration,
} from './format'

interface SummaryGridProps {
  summary: StatisticsSummary
}

interface MetricItem {
  label: string
  value: string
  detail: string
  icon: LucideIcon
  color: string
}

export function SummaryGrid({ summary }: SummaryGridProps) {
  const metrics: MetricItem[] = [
    {
      label: '请求总数',
      value: formatCompactNumber(summary.total_requests),
      detail: `平均 ${summary.avg_response_time.toFixed(2)} 秒`,
      icon: Activity,
      color: 'ios-symbol-blue',
    },
    {
      label: 'Token 总量',
      value: formatCompactNumber(summary.total_tokens),
      detail: `${formatCompactNumber(summary.tokens_per_hour)} / 小时`,
      icon: Database,
      color: 'ios-symbol-purple',
    },
    {
      label: '累计花费',
      value: formatCompactCurrency(summary.total_cost),
      detail: `${formatCurrency(summary.cost_per_hour)} / 小时`,
      icon: DollarSign,
      color: 'ios-symbol-green',
    },
    {
      label: '消息总数',
      value: formatCompactNumber(summary.total_messages),
      detail: '接收与发送消息',
      icon: MessageSquare,
      color: 'ios-symbol-orange',
    },
    {
      label: '回复总数',
      value: formatCompactNumber(summary.total_replies),
      detail: '已完成回复动作',
      icon: Zap,
      color: 'ios-symbol-teal',
    },
    {
      label: '在线时间',
      value: formatDuration(summary.online_time),
      detail: '所选时间范围内',
      icon: Clock,
      color: 'ios-symbol-gray',
    },
    {
      label: '消息回复率',
      value:
        summary.total_messages > 0
          ? `${((summary.total_replies / summary.total_messages) * 100).toFixed(1)}%`
          : '0%',
      detail: '回复数 / 消息数',
      icon: Gauge,
      color: 'ios-symbol-pink',
    },
    {
      label: '每请求 Token',
      value:
        summary.total_requests > 0
          ? formatCompactNumber(summary.total_tokens / summary.total_requests)
          : '0',
      detail: '平均单次消耗',
      icon: TrendingUp,
      color: 'ios-symbol-yellow',
    },
  ]

  return (
    <section aria-label="统计摘要" className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
      {metrics.map(({ label, value, detail, icon: Icon, color }) => (
        <article key={label} className="ios-stat-card relative min-w-0">
          <p className="min-w-0 pr-11 text-[13px] font-medium leading-5 text-muted-foreground">
            {label}
          </p>
          <span
            className={`ios-symbol ios-symbol-md absolute right-4 top-4 sm:right-5 sm:top-5 ${color}`}
            aria-hidden="true"
          >
            <Icon className="h-4 w-4" />
          </span>
          <p className="mt-2 whitespace-nowrap text-[21px] font-semibold leading-7 text-foreground sm:text-[25px]">
            {value}
          </p>
          <p className="mt-3 text-[12px] leading-5 text-muted-foreground">{detail}</p>
        </article>
      ))}
    </section>
  )
}
