export type RestartPollResult = 'success' | 'failed' | 'cancelled'

type RestartHealthCheck = (signal: AbortSignal) => Promise<boolean>
type RestartWait = (delayMs: number, signal: AbortSignal) => Promise<boolean>

interface PollRestartHealthOptions {
  check: RestartHealthCheck
  signal: AbortSignal
  maxAttempts: number
  retryDelayMs: number
  onAttempt?: (attempt: number) => void
  wait?: RestartWait
}

export function waitForRestartDelay(delayMs: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false)

  return new Promise((resolve) => {
    const finish = (completed: boolean) => {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', handleAbort)
      resolve(completed)
    }
    const handleAbort = () => finish(false)
    const timer = window.setTimeout(() => finish(true), delayMs)
    signal.addEventListener('abort', handleAbort, { once: true })
  })
}

export async function pollRestartHealth({
  check,
  signal,
  maxAttempts,
  retryDelayMs,
  onAttempt,
  wait = waitForRestartDelay,
}: PollRestartHealthOptions): Promise<RestartPollResult> {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (signal.aborted) return 'cancelled'
    onAttempt?.(attempt)

    try {
      if (await check(signal)) return 'success'
    } catch {
      if (signal.aborted) return 'cancelled'
    }

    if (attempt < maxAttempts && !(await wait(retryDelayMs, signal))) return 'cancelled'
  }

  return 'failed'
}
