import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { RecentActivity as RecentActivityItem } from '@/types/statistics'
import { formatCompactNumber, formatCurrency, formatDateTime } from './format'

function getStatusLabel(status: string): string {
  if (status === 'success') return '成功'
  if (status === 'failed' || status === 'error') return '失败'
  return status
}

export function RecentActivity({ rows }: { rows: RecentActivityItem[] }) {
  if (rows.length === 0) {
    return (
      <div className="ios-empty-state" role="status">
        <p className="text-[15px] font-semibold text-foreground">所选时段暂无请求记录</p>
      </div>
    )
  }

  return (
    <div className="ios-table-surface overflow-hidden">
      <Table aria-label="最近请求记录" className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead>时间</TableHead>
            <TableHead>模型</TableHead>
            <TableHead>请求类型</TableHead>
            <TableHead className="text-right">Token</TableHead>
            <TableHead className="text-right">花费</TableHead>
            <TableHead className="text-right">耗时</TableHead>
            <TableHead className="text-right">状态</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.timestamp}-${row.model}-${index}`}>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatDateTime(row.timestamp)}
              </TableCell>
              <TableCell className="font-medium">{row.model}</TableCell>
              <TableCell className="max-w-[260px]">
                <span className="ios-break-anywhere">{row.request_type}</span>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatCompactNumber(row.tokens)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatCurrency(row.cost, 4)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.time_cost.toFixed(2)} 秒
              </TableCell>
              <TableCell className="text-right">
                <Badge variant={row.status === 'success' ? 'secondary' : 'destructive'}>
                  {getStatusLabel(row.status)}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
