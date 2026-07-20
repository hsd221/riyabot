export function formatTraceOperation(operation: string): string {
  if (operation === 'response') return '对话'
  if (operation === 'embedding') return '向量'
  if (operation === 'audio') return '语音'
  return operation
}

export function formatTraceDuration(durationMs: number | null): string {
  if (durationMs === null) return '进行中'
  if (durationMs < 1000) return `${durationMs} ms`
  return `${(durationMs / 1000).toFixed(durationMs < 10_000 ? 2 : 1)} s`
}
