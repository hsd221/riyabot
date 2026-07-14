import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { LLMStatistics } from '@/types/statistics'
import { formatCompactNumber, formatCurrency, formatExactNumber } from './format'

export interface BreakdownRow extends LLMStatistics {
  name: string
}

interface BreakdownTableProps {
  rows: BreakdownRow[]
  nameLabel: string
}

export function BreakdownTable({ rows, nameLabel }: BreakdownTableProps) {
  if (rows.length === 0) {
    return (
      <div className="ios-empty-state" role="status">
        <p className="text-[15px] font-semibold text-foreground">暂无聚合数据</p>
      </div>
    )
  }

  return (
    <div className="ios-table-surface overflow-hidden">
      <Table aria-label={`${nameLabel}统计`} className="min-w-[820px]">
        <TableHeader>
          <TableRow>
            <TableHead>{nameLabel}</TableHead>
            <TableHead className="text-right">请求数</TableHead>
            <TableHead className="text-right">输入 Token</TableHead>
            <TableHead className="text-right">输出 Token</TableHead>
            <TableHead className="text-right">Token 总量</TableHead>
            <TableHead className="text-right">花费</TableHead>
            <TableHead className="text-right">平均耗时</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.name}>
              <TableCell className="max-w-[260px] font-medium">
                <span className="ios-break-anywhere">{row.name}</span>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatExactNumber(row.request_count)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatCompactNumber(row.prompt_tokens)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatCompactNumber(row.completion_tokens)}
              </TableCell>
              <TableCell className="text-right font-medium tabular-nums">
                {formatCompactNumber(row.total_tokens)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatCurrency(row.total_cost, 4)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.avg_response_time.toFixed(2)} 秒
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
