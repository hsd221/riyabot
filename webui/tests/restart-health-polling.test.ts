import { describe, expect, it } from 'bun:test'
import { pollRestartHealth } from '../src/lib/restart-health-polling'

const skipDelay = async () => true

describe('restart health polling', () => {
  it('stops after the first successful health check', async () => {
    const attempts: number[] = []
    let checks = 0

    const result = await pollRestartHealth({
      check: async () => {
        checks += 1
        return checks === 3
      },
      signal: new AbortController().signal,
      maxAttempts: 60,
      retryDelayMs: 2000,
      onAttempt: (attempt) => attempts.push(attempt),
      wait: skipDelay,
    })

    expect(result).toBe('success')
    expect(checks).toBe(3)
    expect(attempts).toEqual([1, 2, 3])
  })

  it('enforces the configured retry limit', async () => {
    let checks = 0

    const result = await pollRestartHealth({
      check: async () => {
        checks += 1
        return false
      },
      signal: new AbortController().signal,
      maxAttempts: 4,
      retryDelayMs: 2000,
      wait: skipDelay,
    })

    expect(result).toBe('failed')
    expect(checks).toBe(4)
  })

  it('cancels without scheduling another check after abort', async () => {
    const controller = new AbortController()
    let checks = 0
    let waits = 0

    const result = await pollRestartHealth({
      check: async () => {
        checks += 1
        controller.abort()
        throw new DOMException('cancelled', 'AbortError')
      },
      signal: controller.signal,
      maxAttempts: 60,
      retryDelayMs: 2000,
      wait: async () => {
        waits += 1
        return true
      },
    })

    expect(result).toBe('cancelled')
    expect(checks).toBe(1)
    expect(waits).toBe(0)
  })
})
