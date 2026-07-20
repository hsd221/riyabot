export interface ModelPieLegendItem {
  name: string
  value: number
  fill: string
}

export function ModelPieLegend({ data }: { data: ModelPieLegendItem[] }) {
  const total = data.reduce((sum, item) => sum + item.value, 0)

  return (
    <ul
      aria-label="模型请求占比"
      className="grid gap-x-4 gap-y-2 border-t border-border/60 pt-4 sm:hidden"
    >
      {data.map((item, index) => {
        const percentage = total > 0 ? Math.round((item.value / total) * 100) : 0

        return (
          <li
            key={`${item.name}-${index}`}
            className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 text-[13px] leading-5"
          >
            <span
              aria-hidden="true"
              className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: item.fill }}
            />
            <span className="ios-break-anywhere min-w-0 text-foreground">{item.name}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground">{percentage}%</span>
          </li>
        )
      })}
    </ul>
  )
}
