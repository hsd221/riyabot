import { Progress } from '@/components/ui/progress'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { ChatStatistics } from '@/types/statistics'
import { formatExactNumber } from './format'

export function ChatTable({ rows }: { rows: ChatStatistics[] }) {
  const totalMessages = rows.reduce((total, row) => total + row.message_count, 0)

  if (rows.length === 0) {
    return (
      <div className="ios-empty-state" role="status">
        <p className="text-[15px] font-semibold text-foreground">暂无聊天数据</p>
      </div>
    )
  }

  return (
    <div className="ios-table-surface overflow-hidden">
      <Table aria-label="聊天消息统计" className="min-w-[620px]">
        <TableHeader>
          <TableRow>
            <TableHead>聊天</TableHead>
            <TableHead>会话 ID</TableHead>
            <TableHead className="w-[220px]">占比</TableHead>
            <TableHead className="text-right">消息数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const share = totalMessages > 0 ? (row.message_count / totalMessages) * 100 : 0
            return (
              <TableRow key={row.chat_id}>
                <TableCell className="font-medium">{row.chat_name}</TableCell>
                <TableCell className="max-w-[220px] text-muted-foreground">
                  <span className="ios-break-anywhere">{row.chat_id}</span>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-3">
                    <Progress value={share} className="h-2 min-w-24" />
                    <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
                      {share.toFixed(1)}%
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-right font-medium tabular-nums">
                  {formatExactNumber(row.message_count)}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
