import { useState } from 'react'
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { ChartConfig } from '@/components/ui/chart'
import type { TimeSeriesData } from '@/types/statistics'
import { formatCompactNumber, formatSeriesLabel } from './format'

type TrendMetric = 'requests' | 'tokens' | 'cost'

interface TrendChartProps {
  data: TimeSeriesData[]
  granularity: 'hour' | 'day'
}

const chartConfig = {
  requests: { label: '请求数', color: 'hsl(var(--chart-1))' },
  tokens: { label: 'Token', color: 'hsl(var(--chart-3))' },
  cost: { label: '花费', color: 'hsl(var(--chart-2))' },
} satisfies ChartConfig

export function TrendChart({ data, granularity }: TrendChartProps) {
  const [metric, setMetric] = useState<TrendMetric>('requests')

  if (data.length === 0) {
    return (
      <div className="ios-empty-state min-h-[280px]" role="status">
        <p className="text-[15px] font-semibold text-foreground">暂无趋势数据</p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <Tabs value={metric} onValueChange={(value) => setMetric(value as TrendMetric)}>
          <TabsList className="min-h-11">
            <TabsTrigger value="requests" className="min-h-9 px-3">
              请求
            </TabsTrigger>
            <TabsTrigger value="tokens" className="min-h-9 px-3">
              Token
            </TabsTrigger>
            <TabsTrigger value="cost" className="min-h-9 px-3">
              花费
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <ChartContainer config={chartConfig} className="aspect-auto h-[280px] w-full sm:h-[340px]">
        <LineChart
          data={data}
          margin={{ left: 4, right: 12, top: 8, bottom: 4 }}
          accessibilityLayer
        >
          <CartesianGrid vertical={false} stroke="hsl(var(--border) / 0.55)" />
          <XAxis
            dataKey="timestamp"
            axisLine={false}
            tickLine={false}
            minTickGap={32}
            tickFormatter={(value: string) => formatSeriesLabel(value, granularity)}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            width={48}
            tickFormatter={(value: number) => formatCompactNumber(value)}
          />
          <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
          <Line
            type="monotone"
            dataKey={metric}
            stroke={`var(--color-${metric})`}
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ChartContainer>
    </div>
  )
}
