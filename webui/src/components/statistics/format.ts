export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  return new Intl.NumberFormat('zh-CN', {
    notation: Math.abs(value) >= 10_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatExactNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
}

export function formatCurrency(value: number, maximumFractionDigits = 2): string {
  if (!Number.isFinite(value)) return '¥0.00'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits,
  }).format(value)
}

export function formatCompactCurrency(value: number): string {
  if (!Number.isFinite(value)) return '¥0.00'
  if (Math.abs(value) < 10_000) return formatCurrency(value)

  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0 分钟'
  const totalMinutes = Math.floor(seconds / 60)
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60

  if (days > 0) return hours > 0 && days < 10 ? `${days}天 ${hours}时` : `${days}天`
  if (hours > 0) return minutes > 0 ? `${hours}时 ${minutes}分` : `${hours}小时`
  return `${Math.max(minutes, 1)}分钟`
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatSeriesLabel(value: string, granularity: 'hour' | 'day'): string {
  const date = new Date(value)
  if (granularity === 'day') {
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  }
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
